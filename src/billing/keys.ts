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

/**
 * Wallet addresses are stored lowercase. Facilitators disagree on case (PayAI returns
 * lowercase, Coinbase CDP EIP-55 checksummed), and lookups by payer must hit idx_usage_payer
 * with an exact match. Key ids (key_...) pass through unchanged.
 */
export function normalizePayer(payer: string | null): string | null {
  return payer && /^0x[0-9a-fA-F]{40}$/.test(payer) ? payer.toLowerCase() : payer;
}

export async function recordUsage(
  env: Env,
  u: { tool: string; channel: "mcp" | "http"; payment: "credits" | "x402"; payer: string | null; priceMicro: number; ok: boolean; ms: number; tx?: string | null },
): Promise<void> {
  await env.DB.prepare("INSERT INTO usage (tool, channel, payment, payer, price_micro, ok, ms, tx, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
    .bind(u.tool, u.channel, u.payment, normalizePayer(u.payer), u.priceMicro, u.ok ? 1 : 0, u.ms, u.tx ?? null, Date.now())
    .run();
}

// ── Referrals ──────────────────────────────────────────────────────────────

/** Credits a referrer earns, once per referred key, when that key first pays for a top-up. */
export const REFERRAL_REWARD_MICRO = 1_000_000;

/** The key's referral code, created on first use. */
export async function referralCode(env: Env, keyId: string): Promise<string> {
  const row = await env.DB.prepare("SELECT referral_code FROM api_keys WHERE id = ?").bind(keyId).first<{ referral_code: string | null }>();
  if (row?.referral_code) return row.referral_code;
  for (let i = 0; i < 3; i++) {
    const code = randomToken(8);
    const r = await env.DB.prepare("UPDATE api_keys SET referral_code = ? WHERE id = ? AND referral_code IS NULL").bind(code, keyId).run().catch(() => null);
    if (r?.meta.changes) return code;
  }
  const again = await env.DB.prepare("SELECT referral_code FROM api_keys WHERE id = ?").bind(keyId).first<{ referral_code: string | null }>();
  return again?.referral_code ?? "";
}

/** Link a new key to its referrer. Ignored for unknown codes and same-origin (self) referrals. */
export async function linkReferral(env: Env, newKeyId: string, code: string | undefined, creatorHash: string | undefined) {
  if (!code || !/^[A-Za-z0-9]{6,16}$/.test(code)) return false;
  const ref = await env.DB.prepare("SELECT id, creator_hash FROM api_keys WHERE referral_code = ? AND disabled = 0").bind(code).first<{ id: string; creator_hash: string | null }>();
  if (!ref || ref.id === newKeyId || (creatorHash && ref.creator_hash === creatorHash)) return false;
  await env.DB.prepare("UPDATE api_keys SET referred_by = ? WHERE id = ? AND referred_by IS NULL").bind(ref.id, newKeyId).run();
  return true;
}

/** After a paid top-up: reward the referrer once. The ledger's unique ref makes this idempotent. */
export async function rewardReferrer(env: Env, paidKeyId: string) {
  const row = await env.DB.prepare("SELECT referred_by FROM api_keys WHERE id = ?").bind(paidKeyId).first<{ referred_by: string | null }>();
  if (!row?.referred_by) return false;
  return addCredits(env, row.referred_by, REFERRAL_REWARD_MICRO, "referral", `referral:${paidKeyId}`);
}

const codeMemo = new Map<string, string>();

/** The referral code for a raw API key, or undefined if the key isn't valid. Memoized per isolate. */
export async function referralCodeForKey(env: Env, rawKey: string | null | undefined): Promise<string | undefined> {
  if (!rawKey) return undefined;
  const memoKey = await sha256Hex(rawKey); // never keep raw secrets in isolate memory
  const hit = codeMemo.get(memoKey);
  if (hit) return hit;
  const key = await findApiKey(env, rawKey).catch(() => null);
  if (!key) return undefined;
  const code = await referralCode(env, key.id).catch(() => "");
  if (!code) return undefined;
  if (codeMemo.size > 5000) codeMemo.clear();
  codeMemo.set(memoKey, code);
  return code;
}
