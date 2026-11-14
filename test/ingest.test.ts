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
