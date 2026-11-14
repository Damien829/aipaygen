import { describe, expect, it } from "vitest";
import { normalizeDescription, x402ItemId } from "../src/refresh";

describe("x402 feed dedupe", () => {
  const desc = "Real-time token price, volume and liquidity for any ERC-20 on Base.";
  it("groups one host's paths that share a real description", async () => {
    const a = await x402ItemId("https://api.seller.xyz/price/eth", desc);
    const b = await x402ItemId("https://api.seller.xyz/price/btc", desc.toUpperCase() + "  ");
    expect(a.grouped).toBe(true);
    expect(a.id).toBe(b.id);
    expect(a.id.startsWith("api:x402g-")).toBe(true);
  });
  it("keeps other hosts and short descriptions apart", async () => {
    const a = await x402ItemId("https://api.seller.xyz/price/eth", desc);
    const other = await x402ItemId("https://other.example/price", desc);
    expect(other.id).not.toBe(a.id);
    const s1 = await x402ItemId("https://api.seller.xyz/a", "Paid API");
    const s2 = await x402ItemId("https://api.seller.xyz/b", "Paid API");
    expect(s1.grouped).toBe(false);
    expect(s1.id).not.toBe(s2.id);
  });
  it("normalizes case and punctuation", () => {
    expect(normalizeDescription("  Hello, WORLD!! v2 ")).toBe("hello world v2");
  });
});

import { parseQuote } from "../src/refresh";

describe("x402 quote check", () => {
  const v2 = { x402Version: 2, accepts: [{ scheme: "exact", network: "eip155:8453", asset: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", payTo: "0xebA22e8CD05Cb72A2F913099D6cCA666DD6D35B0", amount: "1000" }] };
  it("accepts a v2 PAYMENT-REQUIRED header and a v1 body", () => {
    expect(parseQuote(btoa(JSON.stringify(v2)), "")).toBe(true);
    const v1 = { accepts: [{ scheme: "exact", network: "base", payTo: "0xebA22e8CD05Cb72A2F913099D6cCA666DD6D35B0", maxAmountRequired: "5000" }] };
    expect(parseQuote(null, JSON.stringify(v1))).toBe(true);
  });
  it("rejects quotes missing who to pay or how much", () => {
    expect(parseQuote(null, '{"accepts": []}')).toBe(false);
    expect(parseQuote(null, JSON.stringify({ accepts: [{ ...v2.accepts[0], payTo: "" }] }))).toBe(false);
    expect(parseQuote(null, JSON.stringify({ accepts: [{ ...v2.accepts[0], amount: "free" }] }))).toBe(false);
    expect(parseQuote("not base64!", "<html>402</html>")).toBe(false);
  });
});
