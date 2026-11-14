import { afterEach, describe, expect, it, vi } from "vitest";
import { CORE_ROUTES, corePrice, handleCore, signCoreRequest } from "../src/core/proxy";
import type { Env } from "../src/env";

const env = (over: Partial<Env> = {}) =>
  ({ PUBLIC_URL: "https://aipaygen.com", CORE_ORIGIN: "https://core.example", CORE_EDGE_SECRET: "test-secret", PAY_TO: "", ...over }) as unknown as Env;

afterEach(() => vi.unstubAllGlobals());

describe("core proxy", () => {
  it("signs exactly like core/edge_auth.py", async () => {
    // Same vector is asserted in core/tests/test_edge_auth.py.
    const sig = await signCoreRequest("test-secret", "1700000000", "post", "/research?x=1%20y", new TextEncoder().encode('{"topic":"agents"}'), "x402", "203.0.113.9");
    expect(sig).toBe("cf3fea3b5a1df7ce59cc7bf4841cfa4bdb265bc05dd2b5e60e88ca699fff22e5");
  });

  it("loads the shared price table", () => {
    expect(CORE_ROUTES.length).toBeGreaterThan(150);
    expect(corePrice("post", "/research")?.price_micro).toBeGreaterThan(0);
    expect(corePrice("GET", "/market")).toBeUndefined();
  });

  it("is off until the core is configured", async () => {
    expect(await handleCore(new Request("https://aipaygen.com/market"), env({ CORE_ORIGIN: undefined }))).toBeNull();
  });

  it("forwards free routes signed, without client identity claims or Worker keys", async () => {
    const fetchMock = vi.fn(async () => new Response("<html>ok</html>", { headers: { "content-type": "text/html" } }));
    vi.stubGlobal("fetch", fetchMock);
    const req = new Request("https://aipaygen.com/market?page=2", {
      headers: { "cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "6.6.6.6", "x-aipaygen-paid": "credits", authorization: "Bearer apg_abcdefghijklmnopqrstuv" },
    });
    const res = await handleCore(req, env());
    expect(await res!.text()).toBe("<html>ok</html>");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(String(url)).toBe("https://core.example/market?page=2");
    const h = new Headers(init.headers);
    expect(h.get("x-aipaygen-paid")).toBe("free");
    expect(h.get("x-aipaygen-client-ip")).toBe("203.0.113.9");
    expect(h.get("x-forwarded-for")).toBeNull();
    expect(h.get("authorization")).toBeNull();
    const ts = h.get("x-aipaygen-edge-ts")!;
    expect(h.get("x-aipaygen-edge-sig")).toBe(await signCoreRequest("test-secret", ts, "GET", "/market?page=2", new Uint8Array(), "free", "203.0.113.9"));
  });

  it("never forwards a priced route that hasn't been paid", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const req = new Request("https://aipaygen.com/research", { method: "POST", body: '{"topic":"x"}', headers: { "content-type": "application/json" } });
    const res = await handleCore(req, env());
    expect(res!.status).toBe(402);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
