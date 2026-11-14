import { describe, expect, it } from "vitest";
import { monitoredTools } from "../src/monitor";
import { TOOLS } from "../src/tools";

describe("own-tool monitor", () => {
  it("checks paid tools with examples and skips AI and composite ones", () => {
    const names = monitoredTools().map((t) => t.name);
    expect(names.length).toBeGreaterThan(30);
    expect(names).toContain("dns_lookup");
    expect(names).toContain("sec_filings");
    for (const skipped of ["generate_image", "ask_llm", "domain_report", "find_tool", "search_marketplace"]) expect(names).not.toContain(skipped);
    expect(monitoredTools().every((t) => t.priceMicro > 0 && TOOLS.includes(t))).toBe(true);
  });
});
