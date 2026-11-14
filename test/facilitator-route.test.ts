import { afterEach, describe, expect, it, vi } from "vitest";
import { settleUpstream, upstreams } from "../src/facilitator";
import type { Env } from "../src/env";

const env = { CDP_API_KEY_ID: undefined, CDP_API_KEY_SECRET: undefined } as unknown as Env;
const body = { x402Version: 2, paymentPayload: {} as never, paymentRequirements: { network: "eip155:8453" } as never };
const reply = (status: number, b: object) => new Response(JSON.stringify(b), { status, headers: { "content-type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("facilitator routing", () => {
  it("uses PayAI first, and Coinbase only when its key is set", () => {
    expect(upstreams(env).map((u) => u.name)).toEqual(["payai"]);
    expect(upstreams({ ...env, CDP_API_KEY_ID: "k", CDP_API_KEY_SECRET: "s" } as Env).map((u) => u.name)).toEqual(["payai", "cdp"]);
  });
  it("returns the first successful settlement and which network carried it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(200, { success: true, transaction: "0xabc", network: "eip155:8453", payer: "0x1" })));
    expect(await settleUpstream(env, body)).toMatchObject({ via: "payai", result: { success: true, transaction: "0xabc" } });
  });
  it("does not retry elsewhere when the payment itself is bad", async () => {
    const f = vi.fn(async () => reply(400, { success: false, errorReason: "invalid_exact_evm_payload_signature" }));
    vi.stubGlobal("fetch", f);
    const r = await settleUpstream({ ...env, CDP_API_KEY_ID: "k", CDP_API_KEY_SECRET: "s" } as Env, body);
    expect(r.result.errorReason).toBe("invalid_exact_evm_payload_signature");
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("reports unreachable when every upstream is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }));
    expect((await settleUpstream(env, body)).result.errorReason).toBe("upstream_unreachable");
  });
});
