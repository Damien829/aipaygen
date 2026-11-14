import type { Env } from "./env";
import { openIssue } from "./lib/github";

/**
 * Payment reconciliation: checks that every x402 payment we recorded as settled
 * really landed on-chain. For each one it reads the transaction receipt and looks
 * for a successful USDC Transfer to the right wallet for at least the right amount.
 *
 * Covers both our own paid calls (usage, paid to PAY_TO on X402_NETWORK) and
 * settlements our facilitator submitted for merchants (facilitator_settlements).
 * Works through them a few per cron run (free-plan subrequest limit), oldest first,
 * and only once a payment is 10 minutes old so it has had time to confirm.
 */

// Free public RPCs, tried in order: Base's own endpoint often rate-limits Cloudflare's IPs.
const NETWORKS: Record<string, { rpcs: (env: Env) => string[]; usdc: string }> = {
  "eip155:8453": {
    rpcs: (env) => [env.FACILITATOR_RPC_BASE, "https://base-rpc.publicnode.com", "https://1rpc.io/base", "https://mainnet.base.org"].filter((u): u is string => !!u),
    usdc: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
  },
  "eip155:84532": {
    rpcs: (env) => [env.FACILITATOR_RPC_BASE_SEPOLIA, "https://sepolia.base.org", "https://base-sepolia-rpc.publicnode.com"].filter((u): u is string => !!u),
    usdc: "0x036cbd53842c5426634e7929541ec2318f3dcf7e",
  },
};
const TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const PER_RUN = 8; // RPC calls per cron run
const SETTLE_DELAY = 10 * 60_000;
const KEEP_MISSING = 20;

export interface Payment {
  source: "sale" | "facilitator";
  id: number;
  network: string;
  tx: string;
  pay_to: string;
  amount_micro: number;
  created_at: number;
}

export interface Receipt {
  status: string;
  logs: { address: string; topics: string[]; data: string }[];
}

export type Verdict = "confirmed" | "pending" | "failed" | "not_found" | "wrong_transfer" | "unknown_network";

/** Pure check of one receipt against what we expected to be paid. */
export function judge(p: Payment, receipt: Receipt | null): Verdict {
  const net = NETWORKS[p.network];
  if (!net) return "unknown_network";
  if (!receipt) return "not_found";
  if (receipt.status !== "0x1") return "failed";
  const to = "0x" + p.pay_to.toLowerCase().replace(/^0x/, "").padStart(64, "0");
  const paid = receipt.logs.some((l) =>
    l.address.toLowerCase() === net.usdc &&
    l.topics[0]?.toLowerCase() === TRANSFER &&
    l.topics[2]?.toLowerCase() === to &&
    BigInt(l.data === "0x" ? 0 : l.data) >= BigInt(p.amount_micro));
  return paid ? "confirmed" : "wrong_transfer";
}

async function getReceipt(env: Env, p: Payment): Promise<Receipt | null> {
  const net = NETWORKS[p.network];
  if (!net) return null;
  let last = "no rpc";
  for (const url of net.rpcs(env)) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getTransactionReceipt", params: [p.tx] }),
        signal: AbortSignal.timeout(6_000),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const j = (await res.json()) as { result?: Receipt | null; error?: { message?: string } };
      if (j.error) throw new Error(j.error.message ?? "error");
      return j.result ?? null;
    } catch (err) {
      last = `${new URL(url).hostname}: ${err instanceof Error ? err.message : String(err)}`.slice(0, 120);
    }
  }
  throw new Error(`rpc ${last}`);
}

interface State {
  sale_cursor: number; // usage.created_at of the last sale checked
  fac_cursor: number; // facilitator_settlements.id of the last one checked
  confirmed: number;
  problems: number;
  missing: (Pick<Payment, "source" | "network" | "tx" | "amount_micro" | "created_at"> & { verdict: Verdict })[];
  checked_at: string | null;
}

const EMPTY: State = { sale_cursor: 0, fac_cursor: 0, confirmed: 0, problems: 0, missing: [], checked_at: null };

export async function reconcileState(env: Env): Promise<State> {
  const r = await env.DB.prepare("SELECT value FROM sync_state WHERE key = 'reconcile'").first<{ value: string }>();
  try {
    return { ...EMPTY, ...(JSON.parse(r?.value ?? "{}") as Partial<State>) };
  } catch {
    return { ...EMPTY };
  }
}

export async function reconcilePayments(env: Env) {
  const state = await reconcileState(env);
  const before = Date.now() - SETTLE_DELAY;
  // First run starts from the last 7 days rather than the whole history.
  if (!state.sale_cursor) state.sale_cursor = Date.now() - 7 * 86_400_000;
  // Sales before PAY_TO took effect went to an earlier wallet; only check from then on.
  const since = Date.parse(env.PAY_TO_SINCE ?? "");
  if (since > state.sale_cursor) state.sale_cursor = since;

  const [sales, fac] = await env.DB.batch([
    env.DB.prepare(
      `SELECT id, tx, price_micro AS amount_micro, created_at FROM usage
       WHERE created_at > ? AND created_at < ? AND payment = 'x402' AND ok = 1 AND tx IS NOT NULL AND tx != ''
       ORDER BY created_at LIMIT ${PER_RUN}`,
    ).bind(state.sale_cursor, before),
    env.DB.prepare(
      `SELECT id, network, tx, pay_to, CAST(amount AS INTEGER) AS amount_micro, created_at FROM facilitator_settlements
       WHERE id > ? AND created_at < ? AND success = 1 AND tx != '' ORDER BY id LIMIT ${PER_RUN}`,
    ).bind(state.fac_cursor, before),
  ]);
  const queue: Payment[] = [
    ...(sales!.results as { id: number; tx: string; amount_micro: number; created_at: number }[]).map((r) => ({
      source: "sale" as const, network: env.X402_NETWORK, pay_to: env.PAY_TO, ...r,
    })),
    ...(fac!.results as Omit<Payment, "source">[]).map((r) => ({ source: "facilitator" as const, ...r })),
  ].sort((a, b) => a.created_at - b.created_at).slice(0, PER_RUN);

  const found: State["missing"] = [];
  let confirmed = 0;
  let stalled: string | undefined;
  for (const p of queue) {
    let verdict: Verdict;
    try {
      verdict = judge(p, await getReceipt(env, p));
    } catch (err) {
      stalled = err instanceof Error ? err.message : String(err);
      break; // RPC trouble: stop here and retry this one next run
    }
    if (verdict === "confirmed") confirmed++;
    else found.push({ source: p.source, network: p.network, tx: p.tx, amount_micro: p.amount_micro, created_at: p.created_at, verdict });
    if (p.source === "sale") state.sale_cursor = p.created_at;
    else state.fac_cursor = p.id;
  }

  state.confirmed += confirmed;
  state.problems += found.length;
  state.missing = [...found, ...state.missing].slice(0, KEEP_MISSING);
  state.checked_at = new Date().toISOString();
  await env.DB.prepare("INSERT INTO sync_state (key, value, updated_at) VALUES ('reconcile', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
    .bind(JSON.stringify(state), Date.now()).run();

  let alert: string | null | undefined;
  if (found.length) {
    const lines = found.map((m) => `- ${m.source} on ${m.network}: \`${m.tx}\`, ${(m.amount_micro / 1_000_000).toFixed(6)} USDC, ${m.verdict.replace("_", " ")}`);
    alert = await openIssue(
      env,
      `Payments: ${found.length} recorded payment(s) not confirmed on-chain`,
      `Reconciliation couldn't confirm these payments on-chain:\n\n${lines.join("\n")}\n\n"not found" can mean an RPC hiccup; "failed" or "wrong transfer" means the call ran without being paid correctly.`,
      "payments",
    );
  }
  return { checked: confirmed + found.length, confirmed, problems: found.length, ...(stalled ? { stalled } : {}), ...(alert !== undefined ? { alerted: alert === null, ...(alert ? { reason: alert } : {}) } : {}) };
}
