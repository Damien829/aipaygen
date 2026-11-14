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
