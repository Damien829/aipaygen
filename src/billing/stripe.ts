import type { Env } from "../env";
import { addCredits, findApiKey, looksLikeApiKey } from "./keys";

/** Credit packs: what the customer pays (cents) and what they get (micro-USD). */
export const PACKS: Record<string, { cents: number; creditMicro: number; label: string }> = {
  "5": { cents: 500, creditMicro: 5_000_000, label: "$5 of credits" },
  "20": { cents: 2000, creditMicro: 22_000_000, label: "$22 of credits (10% bonus)" },
  "50": { cents: 5000, creditMicro: 57_500_000, label: "$57.50 of credits (15% bonus)" },
};

export function stripeEnabled(env: Env): boolean {
  return Boolean(env.STRIPE_SECRET_KEY && env.STRIPE_WEBHOOK_SECRET);
}

export async function createCheckout(env: Env, rawKey: string, packId: string): Promise<{ url: string } | { error: string; status: number }> {
  if (!stripeEnabled(env)) return { error: "Card payments are not enabled yet.", status: 503 };
  const pack = PACKS[packId];
  if (!pack) return { error: "Unknown credit pack.", status: 400 };
  if (!looksLikeApiKey(rawKey)) return { error: "That API key is not valid.", status: 400 };
  const key = await findApiKey(env, rawKey);
  if (!key) return { error: "That API key is not valid.", status: 400 };

  const form = new URLSearchParams({
    mode: "payment",
    success_url: `${env.PUBLIC_URL}/billing?paid=1`,
    cancel_url: `${env.PUBLIC_URL}/billing`,
    client_reference_id: key.id,
    "metadata[key_id]": key.id,
    "metadata[pack]": packId,
    "line_items[0][quantity]": "1",
    "line_items[0][price_data][currency]": "usd",
    "line_items[0][price_data][unit_amount]": String(pack.cents),
    "line_items[0][price_data][product_data][name]": `AIPayGen credits: ${pack.label}`,
    "payment_intent_data[description]": `AIPayGen credits for ${key.key_prefix}…`,
  });
  const res = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: { authorization: `Bearer ${env.STRIPE_SECRET_KEY}`, "content-type": "application/x-www-form-urlencoded" },
    body: form,
  });
  const data = (await res.json()) as { url?: string; error?: { message?: string } };
  if (!res.ok || !data.url) return { error: "Could not start checkout. Try again shortly.", status: 502 };
  return { url: data.url };
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/** Verify a `Stripe-Signature` header (HMAC-SHA256, 5-minute tolerance). */
export async function verifyStripeSignature(payload: string, header: string | null, secret: string, nowSec = Math.floor(Date.now() / 1000)): Promise<boolean> {
  if (!header) return false;
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=") as [string, string]).filter((p) => p.length === 2));
  const t = Number(parts.t);
  const sigs = header.split(",").filter((p) => p.startsWith("v1=")).map((p) => p.slice(3));
  if (!t || !sigs.length || Math.abs(nowSec - t) > 300) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  for (const sig of sigs) {
    if (!/^[0-9a-f]{64}$/.test(sig)) continue;
    if (await crypto.subtle.verify("HMAC", key, hexToBytes(sig), new TextEncoder().encode(`${t}.${payload}`))) return true;
  }
  return false;
}

interface StripeEvent {
  type: string;
  data: { object: { id: string; payment_status?: string; metadata?: Record<string, string>; amount_total?: number } };
}

/** Apply a verified Stripe webhook. Returns a short status for logs. */
export async function handleStripeWebhook(env: Env, payload: string, signature: string | null): Promise<{ status: number; message: string }> {
  if (!env.STRIPE_WEBHOOK_SECRET) return { status: 503, message: "webhooks disabled" };
  if (!(await verifyStripeSignature(payload, signature, env.STRIPE_WEBHOOK_SECRET))) return { status: 400, message: "bad signature" };
  const event = JSON.parse(payload) as StripeEvent;
  if (event.type !== "checkout.session.completed" && event.type !== "checkout.session.async_payment_succeeded") {
    return { status: 200, message: "ignored" };
  }
  const session = event.data.object;
  if (session.payment_status !== "paid") return { status: 200, message: "not paid yet" };
  const keyId = session.metadata?.key_id;
  const pack = session.metadata?.pack ? PACKS[session.metadata.pack] : undefined;
  if (!keyId || !pack) return { status: 200, message: "missing metadata" };
  const applied = await addCredits(env, keyId, pack.creditMicro, "stripe", `stripe:${session.id}`);
  return { status: 200, message: applied ? "credited" : "already credited" };
}
