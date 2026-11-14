import { describe, expect, it, vi } from "vitest";

// The facilitator is stubbed: every payment verifies and settles.
vi.mock("../src/billing/x402", () => ({
  x402Enabled: () => true,
  microToUsd: (m: number) => `$${m / 1_000_000}`,
  buildRequirements: async () => [{ scheme: "exact" }],
  decodePaymentToken: (t: string) => ({ token: t }),
  verifyPayment: async () => ({ ok: true, match: {}, payer: "0xpayer" }),
  settlePayment: vi.fn(async () => ({ ok: true, transaction: "0xtx", network: "eip155:8453", payer: "0xpayer" })),
  paymentRequiredBody: (_t: unknown, _a: unknown, _u: string, _c: string, error = "PAYMENT_REQUIRED") => ({ error }),
}));

import { chargeAndRun } from "../src/billing/charge";
import * as x402 from "../src/billing/x402";
import type { Env } from "../src/env";
import type { ToolDef } from "../src/tools/types";

/** Just enough D1 for chargeAndRun: payment_claims insert/delete, everything else accepted. */
function fakeDb() {
  const claims = new Set<string>();
  const stmt = (sql: string, args: unknown[] = []) => ({
    bind: (...a: unknown[]) => stmt(sql, a),
    async run() {
      if (sql.startsWith("INSERT OR IGNORE INTO payment_claims")) {
        const had = claims.has(args[0] as string);
        claims.add(args[0] as string);
        return { meta: { changes: had ? 0 : 1 } };
      }
      if (sql.startsWith("DELETE FROM payment_claims")) claims.delete(args[0] as string);
      return { meta: { changes: 1 } };
    },
    async first() { return null; },
    async all() { return { results: [] }; },
  });
  return { prepare: (sql: string) => stmt(sql), batch: async () => [], claims };
}

const tool = (run: () => Promise<Record<string, unknown>>) =>
  ({ name: "t", title: "T", description: "test tool", priceMicro: 1000, cacheTtl: 0, input: {} as never, example: {}, run }) as unknown as ToolDef;

const call = (db: ReturnType<typeof fakeDb>, t: ToolDef, token: string) =>
  chargeAndRun({ env: { DB: db, PUBLIC_URL: "https://x" } as unknown as Env, tool: t, args: {}, channel: "http", payment: { apiKey: null, paymentToken: token }, resourceUrl: "https://x/t" });

describe("x402 payment claims", () => {
  it("runs a payment once; a second copy is refused before any work", async () => {
    const db = fakeDb();
    const run = vi.fn(async () => ({ ok: true }));
    expect((await call(db, tool(run), "pay-1")).kind).toBe("ok");
    const again = await call(db, tool(run), "pay-1");
    expect(again).toMatchObject({ kind: "error", status: 409, code: "PAYMENT_ALREADY_USED" });
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("parallel copies: only one gets the work done", async () => {
    const db = fakeDb();
    const run = vi.fn(async () => ({ ok: true }));
    const results = await Promise.all([call(db, tool(run), "pay-2"), call(db, tool(run), "pay-2"), call(db, tool(run), "pay-2")]);
    expect(results.filter((r) => r.kind === "ok")).toHaveLength(1);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("releases the claim when the tool fails, so an honest retry works", async () => {
    const db = fakeDb();
    const failing = tool(async () => { throw new Error("upstream down"); });
    expect((await call(db, failing, "pay-3")).kind).toBe("error");
    expect(db.claims.size).toBe(0); // claim released
    expect((await call(db, tool(async () => ({ ok: true })), "pay-3")).kind).toBe("ok");
  });

  it("releases the claim when settlement fails", async () => {
    const db = fakeDb();
    vi.mocked(x402.settlePayment).mockResolvedValueOnce({ ok: false, reason: "SETTLE_FAILED" } as never);
    expect((await call(db, tool(async () => ({ ok: true })), "pay-4")).kind).toBe("payment_required");
    expect((await call(db, tool(async () => ({ ok: true })), "pay-4")).kind).toBe("ok");
  });
});
