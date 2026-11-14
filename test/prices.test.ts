import { describe, expect, it } from "vitest";
import { checkPrice, defaultPrice, MAX_PRICE_MICRO, MIN_PRICE_MICRO, parseOverrides } from "../src/prices";

describe("owner price overrides", () => {
  it("knows each tool's code price", () => {
    expect(defaultPrice("company_profile")).toBe(10_000);
    expect(defaultPrice("nope")).toBeUndefined();
  });

  it("accepts prices in range for paid tools", () => {
    expect(checkPrice("company_profile", 20_000)).toBeNull();
    expect(checkPrice("company_profile", MIN_PRICE_MICRO)).toBeNull();
    expect(checkPrice("company_profile", MAX_PRICE_MICRO)).toBeNull();
  });

  it("rejects bad prices, unknown tools and free tools", () => {
    expect(checkPrice("company_profile", MIN_PRICE_MICRO - 1)).toMatch(/between/);
    expect(checkPrice("company_profile", MAX_PRICE_MICRO + 1)).toMatch(/between/);
    expect(checkPrice("company_profile", 1.5)).toMatch(/whole/);
    expect(checkPrice("company_profile", "20000")).toMatch(/whole/);
    expect(checkPrice("nope", 20_000)).toMatch(/No tool/);
    expect(checkPrice("search_marketplace", 20_000)).toMatch(/free/);
  });

  it("drops invalid stored entries instead of applying them", () => {
    expect(parseOverrides('{"company_profile":20000,"dns_lookup":5,"nope":20000,"search_marketplace":3000}')).toEqual({ company_profile: 20_000 });
    expect(parseOverrides("not json")).toEqual({});
    expect(parseOverrides("[1,2]")).toEqual({});
    expect(parseOverrides(null)).toEqual({});
  });
});

import { looksSecret } from "../src/share";

describe("search log never stores secrets", () => {
  it("flags keys and tokens", () => {
    for (const s of [
      "apg_roq1oqcap0qrghhyphqkzv6a9icuaeap496mrdp4",
      "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
      "sk_live_51HabcdefghijklmnopQRST",
      "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
      "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318",
      "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc",
      "my key is Zq8xT2v9LmN4pR7sK1wY6bH3jF5dG0cA please",
    ]) expect(looksSecret(s), s).toBe(true);
  });
  it("keeps normal searches", () => {
    for (const s of ["weather", "translate text between languages", "stripe payments api", "mcp server for postgres", "0x402 facilitator", "a".repeat(40)]) {
      expect(looksSecret(s), s).toBe(false);
    }
  });
});
