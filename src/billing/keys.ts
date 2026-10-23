import type { Env } from "../env";
import { ToolError } from "../lib/errors";

export interface ApiKeyRow {
  id: string;
  key_prefix: string;
  label: string | null;
  balance_micro: number;
  created_at: number;
  disabled: number;
}

const KEYS_PER_CREATOR_PER_DAY = 3;

export async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function randomToken(bytes: number): string {
  const b = crypto.getRandomValues(new Uint8Array(bytes));
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "A").replace(/\//g, "B").replace(/=+$/, "");
}

export function looksLikeApiKey(s: string | null | undefined): s is string {
  return typeof s === "string" && /^apg_[A-Za-z0-9]{20,64}$/.test(s);
}

/** Read an API key from `Authorization: Bearer apg_...` or `X-API-Key`. */
export function apiKeyFromHeaders(headers: Headers | undefined): string | null {
  if (!headers) return null;
  const auth = headers.get("authorization");
  const bearer = auth?.match(/^Bearer\s+(\S+)$/i)?.[1];
  const key = bearer ?? headers.get("x-api-key");
  return looksLikeApiKey(key) ? key : null;
}

/** Create a key with the trial balance. Returns the raw key once; only its hash is stored. */
export async function createApiKey(env: Env, opts: { label?: string; creatorHash?: string }) {
  const now = Date.now();
  if (opts.creatorHash) {
    const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM api_keys WHERE creator_hash = ? AND created_at > ?")
      .bind(opts.creatorHash, now - 86_400_000)
      .first<{ n: number }>();
    if ((row?.n ?? 0) >= KEYS_PER_CREATOR_PER_DAY) {
      throw new ToolError("Daily limit for new free keys reached. Try again tomorrow or top up an existing key.", "KEY_LIMIT", 429);
    }
  }
  const raw = `apg_${randomToken(30)}`;
  const id = `key_${randomToken(12)}`;
  const trial = Math.max(0, Number(env.TRIAL_CREDITS_MICRO) || 0);
  await env.DB.batch([
    env.DB.prepare(
      "INSERT INTO api_keys (id, key_hash, key_prefix, label, balance_micro, created_at, creator_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ).bind(id, await sha256Hex(raw), raw.slice(0, 10), opts.label?.slice(0, 80) ?? null, trial, now, opts.creatorHash ?? null),
    env.DB.prepare("INSERT INTO ledger (key_id, delta_micro, reason, ref, created_at) VALUES (?, ?, 'trial', ?, ?)").bind(id, trial, `trial:${id}`, now),
  ]);
  return { id, api_key: raw, balance_micro: trial };
}

export async function findApiKey(env: Env, raw: string): Promise<ApiKeyRow | null> {
  return env.DB.prepare("SELECT id, key_prefix, label, balance_micro, created_at, disabled FROM api_keys WHERE key_hash = ?")
    .bind(await sha256Hex(raw))
    .first<ApiKeyRow>();
}

/** Atomically take `micro` from a key. Returns the new balance, or null if the balance is too low. */
export async function reserveCredits(env: Env, keyId: string, micro: number): Promise<number | null> {
  const row = await env.DB.prepare(
    "UPDATE api_keys SET balance_micro = balance_micro - ?1 WHERE id = ?2 AND disabled = 0 AND balance_micro >= ?1 RETURNING balance_micro",
  )
    .bind(micro, keyId)
    .first<{ balance_micro: number }>();
  return row ? row.balance_micro : null;
}

/** Give credits back after a failed call. */
export async function refundCredits(env: Env, keyId: string, micro: number): Promise<void> {
  await env.DB.prepare("UPDATE api_keys SET balance_micro = balance_micro + ? WHERE id = ?").bind(micro, keyId).run();
}

/**
 * Add credits exactly once per `ref` (e.g. a Stripe checkout session id).
 * Returns false if this ref was already applied.
 */
export async function addCredits(env: Env, keyId: string, micro: number, reason: string, ref: string): Promise<boolean> {
  const now = Date.now();
  const inserted = await env.DB.prepare("INSERT OR IGNORE INTO ledger (key_id, delta_micro, reason, ref, created_at) VALUES (?, ?, ?, ?, ?)")
    .bind(keyId, micro, reason, ref, now)
    .run();
  if (!inserted.meta.changes) return false;
  await env.DB.prepare("UPDATE api_keys SET balance_micro = balance_micro + ? WHERE id = ?").bind(micro, keyId).run();
  return true;
}

export async function recordUsage(
  env: Env,
  u: { tool: string; channel: "mcp" | "http"; payment: "credits" | "x402"; payer: string | null; priceMicro: number; ok: boolean; ms: number; tx?: string | null },
): Promise<void> {
  await env.DB.prepare("INSERT INTO usage (tool, channel, payment, payer, price_micro, ok, ms, tx, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
    .bind(u.tool, u.channel, u.payment, u.payer, u.priceMicro, u.ok ? 1 : 0, u.ms, u.tx ?? null, Date.now())
    .run();
}
