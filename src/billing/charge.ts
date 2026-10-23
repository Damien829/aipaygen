import type { Env } from "../env";
import { errorMessage, ToolError } from "../lib/errors";
import type { ToolDef } from "../tools/types";
import { findApiKey, recordUsage, refundCredits, reserveCredits } from "./keys";
import {
  buildRequirements,
  decodePaymentToken,
  microToUsd,
  paymentRequiredBody,
  settlePayment,
  verifyPayment,
  x402Enabled,
  type PaymentRequiredBody,
} from "./x402";

export interface PaymentInput {
  apiKey: string | null;
  paymentToken: string | null;
}

export interface Receipt {
  payment: "credits" | "x402" | "free";
  price: string;
  cached: boolean;
  balance_remaining?: string;
  transaction?: string;
  network?: string;
}

export type ChargeOutcome =
  | { kind: "ok"; result: Record<string, unknown>; receipt: Receipt }
  | { kind: "payment_required"; body: PaymentRequiredBody }
  | { kind: "error"; status: number; code: string; message: string; paymentRequired?: PaymentRequiredBody };

const CACHE_ORIGIN = "https://cache.aipaygen.internal";

async function cacheKey(tool: ToolDef, args: unknown): Promise<Request> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(args)));
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return new Request(`${CACHE_ORIGIN}/${tool.name}/${hex}`);
}

function cacheStore(): Cache | null {
  return typeof caches !== "undefined" && "default" in caches ? (caches as unknown as { default: Cache }).default : null;
}

/** Run a tool, serving a fresh-enough cached result when one exists. */
export async function runWithCache(tool: ToolDef, args: Record<string, unknown>, env: Env, ctx?: ExecutionContext) {
  const store = tool.cacheTtl > 0 ? cacheStore() : null;
  const key = store ? await cacheKey(tool, args) : null;
  if (store && key) {
    const hit = await store.match(key);
    if (hit) return { result: (await hit.json()) as Record<string, unknown>, cached: true };
  }
  const result = await tool.run(args, { env });
  if (store && key) {
    const res = new Response(JSON.stringify(result), {
      headers: { "content-type": "application/json", "cache-control": `max-age=${tool.cacheTtl}` },
    });
    const put = store.put(key, res);
    if (ctx) ctx.waitUntil(put);
    else await put;
  }
  return { result, cached: false };
}

/**
 * Charge for and run one tool call. Credits (API key) are tried first, then
 * x402. The caller is only charged when the tool succeeds.
 */
export async function chargeAndRun(opts: {
  env: Env;
  ctx?: ExecutionContext;
  tool: ToolDef;
  args: Record<string, unknown>;
  channel: "mcp" | "http";
  payment: PaymentInput;
  resourceUrl: string;
}): Promise<ChargeOutcome> {
  const { env, ctx, tool, args, channel, payment, resourceUrl } = opts;
  const price = tool.priceMicro;
  const started = Date.now();
  const log = (u: { payment: "credits" | "x402"; payer: string | null; ok: boolean; tx?: string | null }) => {
    const p = recordUsage(env, { tool: tool.name, channel, priceMicro: price, ms: Date.now() - started, ...u }).catch(() => {});
    if (ctx) ctx.waitUntil(p);
  };

  const fail = (err: unknown): ChargeOutcome => {
    const te = err instanceof ToolError ? err : null;
    return { kind: "error", status: te?.status ?? 500, code: te?.code ?? "INTERNAL", message: errorMessage(err) };
  };

  if (price === 0) {
    try {
      const { result, cached } = await runWithCache(tool, args, env, ctx);
      return { kind: "ok", result, receipt: { payment: "free", price: "$0", cached } };
    } catch (err) {
      return fail(err);
    }
  }

  // 1. Prepaid credits.
  if (payment.apiKey) {
    const key = await findApiKey(env, payment.apiKey);
    if (!key || key.disabled) return { kind: "error", status: 401, code: "INVALID_API_KEY", message: "That API key is not valid." };
    const balance = await reserveCredits(env, key.id, price);
    if (balance === null) {
      return {
        kind: "error",
        status: 402,
        code: "INSUFFICIENT_CREDITS",
        message: `This call costs ${microToUsd(price)} and the key's balance is ${microToUsd(key.balance_micro)}. Top up at ${env.PUBLIC_URL}/billing.`,
      };
    }
    try {
      const { result, cached } = await runWithCache(tool, args, env, ctx);
      log({ payment: "credits", payer: key.id, ok: true });
      return { kind: "ok", result, receipt: { payment: "credits", price: microToUsd(price), cached, balance_remaining: microToUsd(balance) } };
    } catch (err) {
      await refundCredits(env, key.id, price);
      log({ payment: "credits", payer: key.id, ok: false });
      return fail(err);
    }
  }

  // 2. x402 pay-per-call.
  if (!x402Enabled(env)) {
    return {
      kind: "error",
      status: 402,
      code: "API_KEY_REQUIRED",
      message: `This tool costs ${microToUsd(price)} per call. Create a free API key (with trial credits) at ${env.PUBLIC_URL}/#get-key or with the create_api_key tool.`,
    };
  }

  let accepts;
  try {
    accepts = await buildRequirements(env, price);
  } catch {
    return { kind: "error", status: 503, code: "PAYMENTS_UNAVAILABLE", message: "The payment facilitator is unavailable. Use an API key or try again shortly." };
  }

  if (!payment.paymentToken) return { kind: "payment_required", body: paymentRequiredBody(tool, accepts, resourceUrl, channel) };

  const payload = decodePaymentToken(payment.paymentToken);
  if (!payload) return { kind: "payment_required", body: paymentRequiredBody(tool, accepts, resourceUrl, channel, "INVALID_PAYMENT") };

  const verified = await verifyPayment(env, payload, accepts);
  if (!verified.ok) return { kind: "payment_required", body: paymentRequiredBody(tool, accepts, resourceUrl, channel, verified.reason) };

  let run: { result: Record<string, unknown>; cached: boolean };
  try {
    run = await runWithCache(tool, args, env, ctx);
  } catch (err) {
    // Not settled, so the payer is not charged.
    log({ payment: "x402", payer: verified.payer, ok: false });
    return fail(err);
  }

  const settled = await settlePayment(env, payload, verified.match);
  if (!settled.ok) return { kind: "payment_required", body: paymentRequiredBody(tool, accepts, resourceUrl, channel, settled.reason) };
  log({ payment: "x402", payer: settled.payer ?? verified.payer, ok: true, tx: settled.transaction });
  return {
    kind: "ok",
    result: run.result,
    receipt: { payment: "x402", price: microToUsd(price), cached: run.cached, transaction: settled.transaction, network: settled.network },
  };
}
