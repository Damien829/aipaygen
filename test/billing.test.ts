import { describe, expect, it } from "vitest";
import { apiKeyFromHeaders, looksLikeApiKey, sha256Hex } from "../src/billing/keys";
import { verifyStripeSignature } from "../src/billing/stripe";
import { microToUsd, toolJsonSchema } from "../src/billing/x402";
import { coerceQuery } from "../src/http";
import { dnsLookup } from "../src/tools/dns";
import { pageToMarkdown } from "../src/tools/page";
import { formatPrice } from "../src/tools/types";

async function stripeSig(payload: string, secret: string, t: number) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${t}.${payload}`));
  return [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

describe("api keys", () => {
  it("validates the key format", () => {
    expect(looksLikeApiKey("apg_abcdefghijklmnopqrstuvwxyz0123")).toBe(true);
    expect(looksLikeApiKey("sk_live_123")).toBe(false);
    expect(looksLikeApiKey("apg_short")).toBe(false);
  });
  it("reads bearer and x-api-key headers", () => {
    const k = "apg_abcdefghijklmnopqrstuvwxyz0123";
    expect(apiKeyFromHeaders(new Headers({ authorization: `Bearer ${k}` }))).toBe(k);
    expect(apiKeyFromHeaders(new Headers({ "x-api-key": k }))).toBe(k);
    expect(apiKeyFromHeaders(new Headers({ authorization: "Bearer nope" }))).toBeNull();
  });
  it("hashes deterministically", async () => {
    expect(await sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});

describe("stripe webhook signatures", () => {
  const secret = "whsec_test";
  const payload = '{"type":"checkout.session.completed"}';
  const now = 1_800_000_000;

  it("accepts a valid signature", async () => {
    const sig = await stripeSig(payload, secret, now);
    expect(await verifyStripeSignature(payload, `t=${now},v1=${sig}`, secret, now)).toBe(true);
  });
  it("rejects a tampered payload", async () => {
    const sig = await stripeSig(payload, secret, now);
    expect(await verifyStripeSignature(`${payload} `, `t=${now},v1=${sig}`, secret, now)).toBe(false);
  });
  it("rejects old timestamps", async () => {
    const sig = await stripeSig(payload, secret, now - 600);
    expect(await verifyStripeSignature(payload, `t=${now - 600},v1=${sig}`, secret, now)).toBe(false);
  });
  it("rejects a missing header", async () => expect(await verifyStripeSignature(payload, null, secret, now)).toBe(false));
});

describe("pricing helpers", () => {
  it("formats prices", () => {
    expect(microToUsd(1000)).toBe("$0.001");
    expect(microToUsd(20_000)).toBe("$0.02");
    expect(microToUsd(5_000_000)).toBe("$5");
    expect(formatPrice(10_000)).toBe("$0.01");
    expect(formatPrice(3000)).toBe("$0.003");
  });
});

describe("http query coercion", () => {
  it("splits arrays and parses numbers", () => {
    expect(coerceQuery(dnsLookup as never, { domain: "a.com", types: "A, MX", junk: "x" })).toEqual({ domain: "a.com", types: ["A", "MX"] });
    expect(coerceQuery(pageToMarkdown as never, { url: "a.com", max_chars: "5000" })).toEqual({ url: "a.com", max_chars: 5000 });
  });
  it("produces JSON schemas", () => {
    const s = toolJsonSchema(dnsLookup as never) as { properties: Record<string, unknown>; required: string[] };
    expect(Object.keys(s.properties)).toEqual(["domain", "types"]);
    expect(s.required).toEqual(["domain"]);
  });
});
