import type { Env } from "../env";
import { addCredits } from "./keys";

/**
 * Referrals for wallet payers. Most x402 buyers pay from a wallet and never create
 * an API key, so the key-based $1 reward never reaches them. Instead:
 *
 *  1. Link: a wallet's first paid call that carries ?ref=CODE links that wallet to
 *     the key owning CODE (one row in payer_refs). Wallets that already paid us
 *     before can't be claimed, so referrers only get credit for new customers.
 *  2. Earn: the referrer gets REF_SHARE of what the linked wallet spends for
 *     REF_WINDOW_DAYS, paid daily as credits. A share of real spend can't be farmed
 *     (it is always less than the spend), unlike a flat reward per wallet.
 */

export const REF_SHARE = 0.2;
export const REF_WINDOW_DAYS = 90;
const DAY = 86_400_000;
const ADDRESS = /^0x[0-9a-f]{40}$/;

/**
 * Links a paying wallet to a referral code if the wallet is new to us. Safe to call on
 * every paid call that carries a ref: it reads at most two small rows and writes one
 * row only the first time. Returns true if a new link was made.
 */
export async function linkPayerRef(env: Pick<Env, "DB">, payer: string | null | undefined, code: string | undefined, now = Date.now()): Promise<boolean> {
  const wallet = payer?.toLowerCase();
  if (!wallet || !ADDRESS.test(wallet) || !code || !/^[A-Za-z0-9]{6,16}$/.test(code)) return false;
  const ref = await env.DB.prepare("SELECT id FROM api_keys WHERE referral_code = ? AND disabled = 0").bind(code).first<{ id: string }>();
  if (!ref) return false;
  // Only new customers: a wallet that paid before this call (allowing for this call's own usage row) stays unclaimed.
  const prior = await env.DB.prepare("SELECT 1 AS x FROM usage WHERE payer = ? AND payment = 'x402' AND ok = 1 AND created_at < ? LIMIT 1")
    .bind(wallet, now - 60_000)
    .first();
  if (prior) return false;
  const r = await env.DB.prepare("INSERT OR IGNORE INTO payer_refs (payer, ref_key_id, first_at) VALUES (?, ?, ?)").bind(wallet, ref.id, now).run();
  return !!r.meta.changes;
}

/** Start of the UTC day containing `t`. */
export const utcDayStart = (t: number) => t - (t % DAY);

/** The referrer's share of a spend in micro-USD, rounded down. */
export const shareOf = (spentMicro: number) => Math.floor(spentMicro * REF_SHARE);

/**
 * Pays every referrer their share of yesterday's spend by linked wallets (or of the day
 * containing `dayStart`). Idempotent: the ledger ref refshare:<key>:<date> is unique,
 * so running twice never pays twice. Call once a day from the cron.
 */
export async function payReferralShares(env: Pick<Env, "DB">, dayStart = utcDayStart(Date.now()) - DAY) {
  const dayEnd = dayStart + DAY;
  const rows = await env.DB.prepare(
    `SELECT r.ref_key_id AS key_id, SUM(u.price_micro) AS spent, COUNT(*) AS calls
     FROM payer_refs r JOIN usage u ON u.payer = r.payer
     WHERE u.payment = 'x402' AND u.ok = 1
       AND u.created_at >= ? AND u.created_at < ?
       AND u.created_at >= r.first_at AND u.created_at < r.first_at + ?
     GROUP BY r.ref_key_id`,
  ).bind(dayStart, dayEnd, REF_WINDOW_DAYS * DAY).all<{ key_id: string; spent: number; calls: number }>();
  const date = new Date(dayStart).toISOString().slice(0, 10);
  let paid = 0;
  let total = 0;
  for (const r of rows.results) {
    const micro = shareOf(r.spent);
    if (micro <= 0) continue;
    if (await addCredits(env as Env, r.key_id, micro, "referral_share", `refshare:${r.key_id}:${date}`)) {
      paid++;
      total += micro;
    }
  }
  return { date, referrers: rows.results.length, paid, total_micro: total };
}

/** What a referrer has from wallet referrals, for /v1/balance. Two small indexed reads. */
export async function referralStats(env: Pick<Env, "DB">, keyId: string) {
  const [wallets, earned] = await env.DB.batch([
    env.DB.prepare("SELECT COUNT(*) AS n FROM payer_refs WHERE ref_key_id = ?").bind(keyId),
    env.DB.prepare("SELECT COALESCE(SUM(delta_micro), 0) AS n FROM ledger WHERE key_id = ? AND reason IN ('referral', 'referral_share')").bind(keyId),
  ]);
  return {
    referred_wallets: (wallets?.results[0] as { n: number } | undefined)?.n ?? 0,
    earned_micro: (earned?.results[0] as { n: number } | undefined)?.n ?? 0,
  };
}
