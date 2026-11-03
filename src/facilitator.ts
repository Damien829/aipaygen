import { x402Facilitator } from "@x402/core/facilitator";
import { toFacilitatorEvmSigner } from "@x402/evm";
import { registerExactEvmScheme } from "@x402/evm/exact/facilitator";
import { createWalletClient, http, publicActions } from "viem";
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

export function facilitatorNetworks(env: Env): ChainId[] {
  return (env.FACILITATOR_NETWORKS ?? "eip155:84532").split(",").map((s) => s.trim()).filter((n): n is ChainId => n in CHAINS);
}

export function facilitatorEnabled(env: Env): boolean {
  return /^0x[0-9a-fA-F]{64}$/.test(env.FACILITATOR_PRIVATE_KEY ?? "") && facilitatorNetworks(env).length > 0;
}

function getFacilitator(env: Env): x402Facilitator {
  const networks = facilitatorNetworks(env);
  const key = `${networks.join(",")}|${env.FACILITATOR_RPC_BASE ?? ""}|${env.FACILITATOR_RPC_BASE_SEPOLIA ?? ""}`;
  if (cached?.key === key) return cached.facilitator;
  const account = privateKeyToAccount(env.FACILITATOR_PRIVATE_KEY as `0x${string}`);
  const facilitator = new x402Facilitator();
  for (const network of networks) {
    const rpc = network === "eip155:8453" ? env.FACILITATOR_RPC_BASE : env.FACILITATOR_RPC_BASE_SEPOLIA;
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
    let result;
    try {
      result = await fac.settle(b.paymentPayload!, b.paymentRequirements!);
    } catch (err) {
      result = { success: false, errorReason: "settle_error", errorMessage: err instanceof Error ? err.message.slice(0, 200) : "error", transaction: "", network: b.paymentRequirements!.network };
    }
    const req = b.paymentRequirements as unknown as { network?: string; payTo?: string; amount?: string; asset?: string };
    const rec = env.DB.prepare(
      "INSERT INTO facilitator_settlements (key_id, network, payer, pay_to, asset, amount, tx, success, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind(key.id, req.network ?? "", (result as { payer?: string }).payer ?? null, req.payTo ?? null, req.asset ?? null, req.amount ?? null,
      (result as { transaction?: string }).transaction ?? "", result.success ? 1 : 0, (result as { errorReason?: string }).errorReason ?? null, Date.now()).run().catch(() => {});
    if (ctx) ctx.waitUntil(rec);
    return json(result, result.success ? 200 : 400);
  }

  return json({ error: "not_found", endpoints: ["GET /facilitator/supported", "POST /facilitator/verify", "POST /facilitator/settle"] }, 404);
}

/** Public volume numbers for /facilitator (and marketing). */
export async function facilitatorStats(env: Env) {
  const r = await env.DB.prepare(
    "SELECT COUNT(*) AS settlements, SUM(success) AS ok, COUNT(DISTINCT pay_to) AS merchants, COUNT(DISTINCT payer) AS payers, SUM(CASE WHEN success = 1 THEN CAST(amount AS INTEGER) ELSE 0 END) AS amount_micro FROM facilitator_settlements",
  ).first<{ settlements: number; ok: number; merchants: number; payers: number; amount_micro: number }>();
  return { settlements: r?.ok ?? 0, merchants: r?.merchants ?? 0, payers: r?.payers ?? 0, volume_usdc: ((r?.amount_micro ?? 0) / 1_000_000).toFixed(2) };
}

