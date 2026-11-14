import { describe, expect, it } from "vitest";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { linkPayerRef, payReferralShares, referralStats, REF_WINDOW_DAYS, shareOf, utcDayStart } from "../src/billing/refshare";

/** A D1-shaped wrapper over node:sqlite, enough for refshare.ts and addCredits. */
function fakeD1() {
  const db = new DatabaseSync(":memory:");
  db.exec(`
    CREATE TABLE api_keys (id TEXT PRIMARY KEY, referral_code TEXT, disabled INTEGER NOT NULL DEFAULT 0, balance_micro INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, key_id TEXT NOT NULL, delta_micro INTEGER NOT NULL, reason TEXT NOT NULL, ref TEXT UNIQUE, created_at INTEGER NOT NULL);
    CREATE TABLE usage (id INTEGER PRIMARY KEY AUTOINCREMENT, tool TEXT, channel TEXT, payment TEXT NOT NULL, payer TEXT, price_micro INTEGER NOT NULL, ok INTEGER NOT NULL, ms INTEGER, tx TEXT, created_at INTEGER NOT NULL);
  `);
  db.exec(readFileSync(new URL("../migrations/0016_payer_refs.sql", import.meta.url), "utf8"));
  const stmt = (sql: string, args: unknown[] = []) => ({
    bind: (...a: unknown[]) => stmt(sql, a),
    first: async <T>() => (db.prepare(sql).get(...(args as never[])) as T) ?? null,
    all: async <T>() => ({ results: db.prepare(sql).all(...(args as never[])) as T[] }),
    run: async () => ({ meta: { changes: Number(db.prepare(sql).run(...(args as never[])).changes) } }),
  });
  const D1 = { prepare: (sql: string) => stmt(sql), batch: async (list: ReturnType<typeof stmt>[]) => Promise.all(list.map((s) => s.all())) };
  return { db, env: { DB: D1 } as never };
}

const W1 = "0x1111111111111111111111111111111111111111";
const W2 = "0x2222222222222222222222222222222222222222";
const DAY = 86_400_000;

describe("wallet-payer referrals", () => {
  it("links only new wallets, to a valid code, once", async () => {
    const { db, env } = fakeD1();
    db.exec("INSERT INTO api_keys (id, referral_code) VALUES ('key_a', 'CODEaaaa'), ('key_off', 'CODEoff1')");
    db.exec("UPDATE api_keys SET disabled = 1 WHERE id = 'key_off'");
    const now = Date.UTC(2026, 10, 14, 12);
    expect(await linkPayerRef(env, W1.toUpperCase().replace("0X", "0x"), "CODEaaaa", now)).toBe(true);
    expect(await linkPayerRef(env, W1, "CODEaaaa", now)).toBe(false); // already linked
    expect(await linkPayerRef(env, W2, "nope1234", now)).toBe(false); // unknown code
    expect(await linkPayerRef(env, W2, "CODEoff1", now)).toBe(false); // disabled key
    expect(await linkPayerRef(env, "not-a-wallet", "CODEaaaa", now)).toBe(false);
    // An existing customer (paid an hour ago) can't be claimed.
    db.prepare("INSERT INTO usage (payment, payer, price_micro, ok, created_at) VALUES ('x402', ?, 1000, 1, ?)").run(W2, now - 3_600_000);
    expect(await linkPayerRef(env, W2, "CODEaaaa", now)).toBe(false);
    expect(db.prepare("SELECT payer FROM payer_refs").all()).toEqual([{ payer: W1 }]);
  });

  it("pays 20% of linked spend inside the window, once per day", async () => {
    const { db, env } = fakeD1();
    db.exec("INSERT INTO api_keys (id, referral_code) VALUES ('key_a', 'CODEaaaa')");
    const linkedAt = Date.UTC(2026, 10, 10, 9);
    db.prepare("INSERT INTO payer_refs (payer, ref_key_id, first_at) VALUES (?, 'key_a', ?)").run(W1, linkedAt);
    const day = utcDayStart(Date.UTC(2026, 10, 13, 15));
    const add = (payer: string, micro: number, t: number, ok = 1, payment = "x402") =>
      db.prepare("INSERT INTO usage (payment, payer, price_micro, ok, created_at) VALUES (?, ?, ?, ?, ?)").run(payment, payer, micro, ok, t);
    add(W1, 10_000, day + 1000);
    add(W1, 5_000, day + 2000);
    add(W1, 9_999, day + 3000, 0); // failed call: not counted
    add(W1, 7_000, day + 4000, 1, "credits"); // not an x402 payment
    add(W2, 50_000, day + 5000); // unlinked wallet
    add(W1, 3_000, day - 1000); // previous day
    const r = await payReferralShares(env, day);
    expect(r).toMatchObject({ referrers: 1, paid: 1, total_micro: shareOf(15_000) });
    expect(shareOf(15_000)).toBe(3_000);
    expect((db.prepare("SELECT balance_micro FROM api_keys WHERE id = 'key_a'").get() as { balance_micro: number }).balance_micro).toBe(3_000);
    // Running the same day again pays nothing more.
    expect((await payReferralShares(env, day)).paid).toBe(0);
    expect((db.prepare("SELECT balance_micro FROM api_keys WHERE id = 'key_a'").get() as { balance_micro: number }).balance_micro).toBe(3_000);
    expect(await referralStats(env, "key_a")).toEqual({ referred_wallets: 1, earned_micro: 3_000 });
  });

  it("stops after the 90-day window", async () => {
    const { db, env } = fakeD1();
    db.exec("INSERT INTO api_keys (id, referral_code) VALUES ('key_a', 'CODEaaaa')");
    const linkedAt = Date.UTC(2026, 0, 1);
    db.prepare("INSERT INTO payer_refs (payer, ref_key_id, first_at) VALUES (?, 'key_a', ?)").run(W1, linkedAt);
    const late = utcDayStart(linkedAt + (REF_WINDOW_DAYS + 1) * DAY);
    db.prepare("INSERT INTO usage (payment, payer, price_micro, ok, created_at) VALUES ('x402', ?, 10000, 1, ?)").run(W1, late + 1000);
    expect((await payReferralShares(env, late)).paid).toBe(0);
  });
});
