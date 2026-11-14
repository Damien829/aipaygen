import { x402Facilitator } from "@x402/core/facilitator";
import { toFacilitatorEvmSigner } from "@x402/evm";
import { registerExactEvmScheme } from "@x402/evm/exact/facilitator";
import { createPublicClient, createWalletClient, http, publicActions } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { base, baseSepolia } from "viem/chains";
import { findApiKey } from "./billing/keys";
import type { Env } from "./env";

/**
 * AIPayGen's x402 facilitator (docs/FACILITATOR.md). Built on the official
 * x402Facilitator + exact EVM scheme. Non-custodial: settle submits the payer's
 * signed EIP-3009 transfer, so USDC moves payer -> merchant directly; our wallet
 * only pays gas.
 *
 *   GET  /facilitator/supported
 *   POST /facilitator/verify   { x402Version, paymentPayload, paymentRequirements }  (open)
 *   POST /facilitator/settle   same body; needs Authorization: Bearer apg_...
 */

const CHAINS = { "eip155:8453": base, "eip155:84532": baseSepolia } as const;
type ChainId = keyof typeof CHAINS;
// Under the Worker's request deadline, so a slow confirmation returns settlement_pending with the hash.
const CONFIRMATION_TIMEOUT_MS = 25_000;

let cached: { key: string; facilitator: x402Facilitator } | null = null;

const MAINNET = "eip155:8453";
// Below this much ETH the mainnet fee wallet stops settling (and says so) instead of failing mid-transaction.
const MIN_GAS_WEI = 20_000_000_000_000n; // 0.00002 ETH, a few settlements' worth

const PAUSED = "paused_no_gas";
const isKey =(k?: string) => /^0x[0-9a-fA-F]{64}$/.test(k ?? "");

/** Mainnet uses its own fee wallet (FACILITATOR_MAINNET_KEY); testnet uses FACILITATOR_PRIVATE_KEY. */
function keyFor(env: Env, network: ChainId): string | undefined {
  return network === MAINNET ? env.FACILITATOR_MAINNET_KEY : env.FACILITATOR_PRIVATE_KEY;
}

/** Configured networks that also have a valid fee-wallet key. */
export function facilitatorNetworks(env: Env): ChainId[] {
  return (env.FACILITATOR_NETWORKS ?? "eip155:84532").split(",").map((s) => s.trim())
    .filter((n): n is ChainId => n in CHAINS).filter((n) => isKey(keyFor(env, n)));
}

export function facilitatorEnabled(env: Env): boolean {
  return facilitatorNetworks(env).length > 0;
}

let pauseCheck: { at: number; paused: boolean } | null = null;

/** Owner switch (POST /admin/facilitator). Cached briefly; other Worker instances catch up within 15 seconds. */
export async function facilitatorPaused(env: Env, fresh = false): Promise<boolean> {
  if (!fresh && pauseCheck && Date.now() - pauseCheck.at < 15_000) return pauseCheck.paused;
  const r = await env.DB.prepare("SELECT value FROM sync_state WHERE key = 'facilitator_paused'").first<{ value: string }>();
  pauseCheck = { at: Date.now(), paused: r?.value === "1" };
  return pauseCheck.paused;
}

export async function setFacilitatorPaused(env: Env, paused: boolean) {
  await env.DB.prepare("INSERT INTO sync_state (key, value, updated_at) VALUES ('facilitator_paused', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
    .bind(paused ? "1" : "0", Date.now()).run();
  pauseCheck = { at: Date.now(), paused };
}

let gasCheck: { at: number; ok: boolean } | null = null;

/** Cached for a minute so busy periods don't add an RPC call per settlement. */
async function mainnetHasGas(env: Env): Promise<boolean> {
  if (gasCheck && Date.now() - gasCheck.at < 60_000) return gasCheck.ok;
  const client = createPublicClient({ chain: base, transport: http(env.FACILITATOR_RPC_BASE) });
  const ok = (await client.getBalance({ address: privateKeyToAccount(env.FACILITATOR_MAINNET_KEY as `0x${string}`).address })) >= MIN_GAS_WEI;
  gasCheck = { at: Date.now(), ok };
  if (!ok) console.log("facilitator mainnet fee wallet low on gas");
  return ok;
}

function getFacilitator(env: Env): x402Facilitator {
  const networks = facilitatorNetworks(env);
  const key = `${networks.join(",")}|${env.FACILITATOR_RPC_BASE ?? ""}|${env.FACILITATOR_RPC_BASE_SEPOLIA ?? ""}|${(env.FACILITATOR_MAINNET_KEY ?? "").slice(-6)}|${(env.FACILITATOR_PRIVATE_KEY ?? "").slice(-6)}`;
  if (cached?.key === key) return cached.facilitator;
  const facilitator = new x402Facilitator();
  for (const network of networks) {
    const account = privateKeyToAccount(keyFor(env, network) as `0x${string}`);
    const rpc = network === MAINNET ? env.FACILITATOR_RPC_BASE : env.FACILITATOR_RPC_BASE_SEPOLIA;
    const client = createWalletClient({ account, chain: CHAINS[network], transport: http(rpc) }).extend(publicActions);
    const signer = toFacilitatorEvmSigner(
      { ...client, address: account.address } as unknown as Parameters<typeof toFacilitatorEvmSigner>[0],
      { confirmationTimeoutMs: CONFIRMATION_TIMEOUT_MS },
    );
    registerExactEvmScheme(facilitator, { signer, networks: network });
  }
  cached = { key, facilitator };
  return facilitator;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "access-control-allow-origin": "*" } });

interface Body {
  x402Version?: number;
  paymentPayload?: Parameters<x402Facilitator["verify"]>[0];
  paymentRequirements?: Parameters<x402Facilitator["verify"]>[1];
}

async function readBody(request: Request): Promise<Body | null> {
  try {
    const b = (await request.json()) as Body;
    return b?.paymentPayload && b?.paymentRequirements ? b : null;
  } catch {
    return null;
  }
}

export async function handleFacilitator(request: Request, env: Env, ctx?: ExecutionContext): Promise<Response> {
  const path = new URL(request.url).pathname.replace(/^\/facilitator/, "") || "/";
  if (!facilitatorEnabled(env)) return json({ error: "facilitator_not_configured" }, 503);
  const fac = getFacilitator(env);
  const networks = facilitatorNetworks(env);
  const served = (b: Body | null) => !!b && (networks as string[]).includes(String((b.paymentRequirements as unknown as { network?: string }).network));

  if (request.method === "GET" && path === "/supported") {
    // The scheme package also lists v1 network names; advertise only networks we actually serve.
    const ours = new Set<string>(networks);
    const v1Names: Record<string, string> = { "eip155:8453": "base", "eip155:84532": "base-sepolia" };
    const v1 = new Set(networks.map((n) => v1Names[n]).filter(Boolean));
    const s = fac.getSupported();
    return json({ ...s, kinds: s.kinds.filter((k) => (k.x402Version >= 2 ? ours.has(k.network) : v1.has(k.network))) });
  }

  if (request.method === "POST" && path === "/verify") {
    const b = await readBody(request);
    if (!b) return json({ isValid: false, invalidReason: "invalid_request", invalidMessage: "Send { x402Version, paymentPayload, paymentRequirements }." }, 400);
    if (!served(b)) return json({ isValid: false, invalidReason: "unsupported_network", invalidMessage: `Supported networks: ${networks.join(", ")}` }, 400);
    try {
      return json(await fac.verify(b.paymentPayload!, b.paymentRequirements!));
    } catch (err) {
      return json({ isValid: false, invalidReason: "verify_error", invalidMessage: err instanceof Error ? err.message.slice(0, 200) : "error" }, 400);
    }
  }

  if (request.method === "POST" && path === "/settle") {
    // Settling costs us gas, so it needs a merchant key (also how we attribute volume).
    const auth = request.headers.get("authorization") ?? "";
    const key = /^Bearer\s+apg_/i.test(auth) ? await findApiKey(env, auth.replace(/^Bearer\s+/i, "")) : null;
    if (!key || key.disabled) return json({ success: false, errorReason: "unauthorized", errorMessage: "Settle needs Authorization: Bearer apg_... (free: POST /v1/keys).", transaction: "", network: "" }, 401);
    if (env.TOOL_LIMITER && !(await env.TOOL_LIMITER.limit({ key: `settle:${key.id}` })).success) {
      return json({ success: false, errorReason: "rate_limited", errorMessage: "Too many settlements. Slow down.", transaction: "", network: "" }, 429);
    }
    const b = await readBody(request);
    if (!b) return json({ success: false, errorReason: "invalid_request", errorMessage: "Send { x402Version, paymentPayload, paymentRequirements }.", transaction: "", network: "" }, 400);
    if (!served(b)) return json({ success: false, errorReason: "unsupported_network", errorMessage: `Supported networks: ${networks.join(", ")}`, transaction: "", network: "" }, 400);
    const req = b.paymentRequirements as unknown as { network?: string; payTo?: string; amount?: string; asset?: string };
    const record = (r: { success: boolean; payer?: string; transaction?: string; errorReason?: string }) => {
      const p = env.DB.prepare(
        "INSERT INTO facilitator_settlements (key_id, network, payer, pay_to, asset, amount, tx, success, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
      ).bind(key.id, req.network ?? "", r.payer ?? null, req.payTo ?? null, req.asset ?? null, req.amount ?? null,
        r.transaction ?? "", r.success ? 1 : 0, r.errorReason ?? null, Date.now()).run().catch(() => {});
      if (ctx) ctx.waitUntil(p);
    };
    if (await facilitatorPaused(env).catch(() => false)) {
      return json({ success: false, errorReason: "facilitator_unavailable", errorMessage: "Settlement is paused by the operator. Retry later or use another facilitator.", transaction: "", network: req.network ?? "" }, 503);
    }
    if (req.network === MAINNET && !(await mainnetHasGas(env).catch(() => false))) {
      // Recorded so the owner can see real demand waiting on the fee wallet (facilitatorAlert).
      record({ success: false, errorReason: PAUSED });
      return json({ success: false, errorReason: "facilitator_unavailable", errorMessage: "Mainnet settlement is paused. Retry later or use another facilitator.", transaction: "", network: MAINNET }, 503);
    }
    let result;
    try {
      result = await fac.settle(b.paymentPayload!, b.paymentRequirements!);
    } catch (err) {
      result = { success: false, errorReason: "settle_error", errorMessage: err instanceof Error ? err.message.slice(0, 200) : "error", transaction: "", network: b.paymentRequirements!.network };
    }
    record(result as { success: boolean; payer?: string; transaction?: string; errorReason?: string });
    return json(result, result.success ? 200 : 400);
  }

  return json({ error: "not_found", endpoints: ["GET /facilitator/supported", "POST /facilitator/verify", "POST /facilitator/settle"] }, 404);
}

/** Public volume numbers for /facilitator, split by network (testnet volume is not real money). */
export async function facilitatorStats(env: Env) {
  const { results } = await env.DB.prepare(
    `SELECT network, SUM(success) AS ok, COUNT(DISTINCT CASE WHEN success = 1 THEN pay_to END) AS merchants, COUNT(DISTINCT CASE WHEN success = 1 THEN payer END) AS payers,
       SUM(CASE WHEN success = 1 THEN CAST(amount AS INTEGER) ELSE 0 END) AS amount_micro,
       COUNT(DISTINCT CASE WHEN error = '${PAUSED}' AND created_at > ? THEN key_id END) AS waiting
     FROM facilitator_settlements GROUP BY network`,
  ).bind(Date.now() - 7 * 86_400_000).all<{ network: string; ok: number; merchants: number; payers: number; amount_micro: number; waiting: number }>();
  const by = (n: string) => results.find((r) => r.network === n);
  const view = (n: string) => {
    const r = by(n);
    return { settlements: r?.ok ?? 0, merchants: r?.merchants ?? 0, payers: r?.payers ?? 0, volume_usdc: ((r?.amount_micro ?? 0) / 1_000_000).toFixed(2) };
  };
  return { mainnet: { ...view(MAINNET), merchants_waiting_7d: by(MAINNET)?.waiting ?? 0 }, testnet: view("eip155:84532") };
}

/**
 * Cron job: when merchants tried real (mainnet) settlements while the fee wallet was
 * empty, open a GitHub issue so the owner knows to fund it. At most once a day.
 * Needs GITHUB_ALERT_TOKEN (fine-grained, Issues: write on the repo); without it, skips.
 */
export async function facilitatorAlert(env: Env) {
  const r = await env.DB.prepare(
    `SELECT COUNT(*) AS attempts, COUNT(DISTINCT key_id) AS merchants, SUM(CAST(amount AS INTEGER)) AS amount_micro
     FROM facilitator_settlements WHERE error = '${PAUSED}' AND created_at > ?`,
  ).bind(Date.now() - 86_400_000).first<{ attempts: number; merchants: number; amount_micro: number | null }>();
  if (!r?.attempts) return { attempts: 0 };
  if (!env.GITHUB_ALERT_TOKEN || !env.GITHUB_ALERT_REPO) return { attempts: r.attempts, alerted: false, reason: "no GITHUB_ALERT_TOKEN" };
  const last = await env.DB.prepare("SELECT value FROM sync_state WHERE key = 'facilitator_alert_at'").first<{ value: string }>();
  if (last && Date.now() - Number(last.value) < 86_400_000) return { attempts: r.attempts, alerted: false, reason: "alerted within a day" };
  const wallet = isKey(env.FACILITATOR_MAINNET_KEY) ? privateKeyToAccount(env.FACILITATOR_MAINNET_KEY as `0x${string}`).address : "(FACILITATOR_MAINNET_KEY not set)";
  const issue = {
    title: `Facilitator: ${r.merchants} merchant(s) tried real payments, fee wallet needs ETH`,
    body: `In the last 24 hours, ${r.attempts} mainnet settlement(s) worth ${((r.amount_micro ?? 0) / 1_000_000).toFixed(2)} USDC from ${r.merchants} merchant key(s) were paused because the fee wallet is low on gas.\n\nSend about $5 of ETH **on Base** to \`${wallet}\`. Settlements resume within a minute.`,
  };
  const post = (body: object) => fetch(`https://api.github.com/repos/${env.GITHUB_ALERT_REPO}/issues`, {
    method: "POST",
    headers: { authorization: `Bearer ${env.GITHUB_ALERT_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "AIPayGenBot", "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10_000),
  });
  let res = await post({ ...issue, labels: ["facilitator"] });
  // Fine-grained tokens with only Issues: write may not be allowed to create a new label; retry without it.
  if (res.status === 403 || res.status === 422) res = await post(issue);
  if (!res.ok) {
    const why = ((await res.json().catch(() => ({}))) as { message?: string }).message ?? "";
    return { attempts: r.attempts, alerted: false, reason: `github ${res.status} ${why}`.trim().slice(0, 200) };
  }
  await env.DB.prepare("INSERT INTO sync_state (key, value, updated_at) VALUES ('facilitator_alert_at', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
    .bind(String(Date.now()), Date.now()).run();
  return { attempts: r.attempts, alerted: true };
}

