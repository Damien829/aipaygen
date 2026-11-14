import type { Env } from "../env";
import { addCredits, findApiKey, rewardReferrer, sha256Hex } from "./keys";
import { buildRequirements, decodePaymentToken, microToUsd, settlePayment, verifyPayment, type PaymentRequiredBody } from "./x402";

/**
 * Prepaid credits bought with x402 (USDC on Base): POST /v1/topup {"amount_usd": 5}
 * with the API key, then again with the signed payment. No card processor needed,
 * and it is the paid top-up that triggers the referrer's reward.
 */

export const TOPUP_MIN_USD = 1;
export const TOPUP_MAX_USD = 100;
/** A referral pays out only on a top-up at least this large, so the reward is never worth farming. */
export const REFERRAL_MIN_TOPUP_MICRO = 5_000_000;

export type TopUpOutcome =
  | { kind: "payment_required"; body: PaymentRequiredBody }
  | { kind: "ok"; credited: string; balance_micro: number; transaction: string; referral_rewarded: boolean }
  | { kind: "error"; status: number; code: string; message: string };

export async function topUp(env: Env, rawKey: string | null, amountUsd: unknown, paymentToken: string | null, resourceUrl: string): Promise<TopUpOutcome> {
  if (!rawKey) return { kind: "error", status: 401, code: "API_KEY_REQUIRED", message: "Send Authorization: Bearer apg_... for the key to top up." };
  const key = await findApiKey(env, rawKey);
  if (!key || key.disabled) return { kind: "error", status: 401, code: "INVALID_API_KEY", message: "That API key is not valid." };
  const usd = Number(amountUsd);
  if (!Number.isFinite(usd) || usd < TOPUP_MIN_USD || usd > TOPUP_MAX_USD) {
    return { kind: "error", status: 400, code: "INVALID_INPUT", message: `amount_usd must be between ${TOPUP_MIN_USD} and ${TOPUP_MAX_USD}.` };
  }
  const micro = Math.round(usd * 100) * 10_000; // whole cents

  let accepts;
  try {
    accepts = await buildRequirements(env, micro);
  } catch {
    return { kind: "error", status: 503, code: "PAYMENTS_UNAVAILABLE", message: "The payment facilitator is unavailable. Try again shortly." };
  }
  const required = (error = "PAYMENT_REQUIRED"): TopUpOutcome => ({
    kind: "payment_required",
    body: {
      x402Version: 2,
      error,
      resource: { url: resourceUrl, description: `Add ${microToUsd(micro)} of prepaid AIPayGen credits to key ${key.key_prefix}…`, mimeType: "application/json" },
      accepts,
    },
  });
  if (!paymentToken) return required();
  const payload = decodePaymentToken(paymentToken);
  if (!payload) return required("INVALID_PAYMENT");
  const verified = await verifyPayment(env, payload, accepts);
  if (!verified.ok) return required(verified.reason);

  // One payment, one top-up, even if it is sent twice at once.
  const claim = await sha256Hex(`x402:${paymentToken}`);
  const claimed = await env.DB.prepare("INSERT OR IGNORE INTO payment_claims (token_hash, created_at) VALUES (?, ?)").bind(claim, Date.now()).run();
  if (!claimed.meta.changes) return { kind: "error", status: 409, code: "PAYMENT_ALREADY_USED", message: "This payment was already used. Sign a new one." };

  const settled = await settlePayment(env, payload, verified.match);
  if (!settled.ok) {
    await env.DB.prepare("DELETE FROM payment_claims WHERE token_hash = ?").bind(claim).run().catch(() => {});
    return required(settled.reason);
  }
  // The ledger ref is unique, so a retried request can't credit the same transaction twice.
  await addCredits(env, key.id, micro, "x402_topup", `x402:${settled.transaction}`);
  const rewarded = micro >= REFERRAL_MIN_TOPUP_MICRO ? await rewardReferrer(env, key.id).catch(() => false) : false;
  const after = await findApiKey(env, rawKey);
  return { kind: "ok", credited: microToUsd(micro), balance_micro: after?.balance_micro ?? key.balance_micro + micro, transaction: settled.transaction, referral_rewarded: !!rewarded };
}
