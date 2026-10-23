import { describe, expect, it } from "vitest";
import { isPrivateIPv4, isPrivateIPv6, normalizeDomain, normalizeUrl } from "../src/lib/net";

describe("normalizeDomain", () => {
  it.each([
    ["Stripe.com", "stripe.com"],
    ["https://www.stripe.com/pricing?x=1", "stripe.com"],
    ["stripe.com.", "stripe.com"],
    ["api.stripe.com:443", "api.stripe.com"],
    ["bücher.de", "xn--bcher-kva.de"],
  ])("%s -> %s", (input, out) => expect(normalizeDomain(input)).toBe(out));

  it.each(["", "localhost", "not_a_domain", "foo", "printer.local", "10.0.0.1", "-bad-.com", "a..b.com"])("rejects %s", (input) => {
    expect(() => normalizeDomain(input)).toThrow();
  });
});

describe("normalizeUrl", () => {
  it("defaults to https", () => expect(normalizeUrl("example.com").toString()).toBe("https://example.com/"));
  it("drops the fragment", () => expect(normalizeUrl("https://example.com/a#b").toString()).toBe("https://example.com/a"));
  it.each([
    "file:///etc/passwd",
    "ftp://example.com",
    "http://localhost/",
    "http://127.0.0.1/",
    "http://169.254.169.254/latest/meta-data",
    "http://[::1]/",
    "http://[::ffff:10.0.0.1]/",
    "http://example.com:8080/",
    "http://user:pass@example.com/",
    "http://service.internal/",
  ])("rejects %s", (u) => expect(() => normalizeUrl(u)).toThrow());
});

describe("private address ranges", () => {
  it.each(["10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.1", "127.0.0.1", "100.64.0.1", "169.254.1.1", "0.0.0.0", "224.0.0.1"])(
    "%s is private",
    (ip) => expect(isPrivateIPv4(ip)).toBe(true),
  );
  it.each(["8.8.8.8", "172.32.0.1", "1.1.1.1", "100.128.0.1"])("%s is public", (ip) => expect(isPrivateIPv4(ip)).toBe(false));
  it("IPv6", () => {
    expect(isPrivateIPv6("::1")).toBe(true);
    expect(isPrivateIPv6("fd00::1")).toBe(true);
    expect(isPrivateIPv6("fe80::1")).toBe(true);
    expect(isPrivateIPv6("2606:4700::1111")).toBe(false);
  });
});
