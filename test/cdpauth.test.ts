import { describe, expect, it } from "vitest";
import { cdpJwt } from "../src/billing/cdpauth";

const b64 = (u: Uint8Array) => btoa(String.fromCharCode(...u));
const fromB64url = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0));

describe("CDP facilitator JWT", () => {
  it("signs an EdDSA JWT scoped to one request that the public key verifies", async () => {
    const pair = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
    const jwk = (await crypto.subtle.exportKey("jwk", pair.privateKey)) as JsonWebKey;
    const secret = b64(new Uint8Array([...fromB64url(jwk.d!), ...fromB64url(jwk.x!)]));
    const jwt = await cdpJwt("key-123", secret, "POST", "https://api.cdp.coinbase.com/platform/v2/x402/settle", 1_800_000_000_000);
    const [h, c, s] = jwt.split(".");
    const header = JSON.parse(new TextDecoder().decode(fromB64url(h!)));
    const claims = JSON.parse(new TextDecoder().decode(fromB64url(c!)));
    expect(header).toMatchObject({ alg: "EdDSA", kid: "key-123", typ: "JWT" });
    expect(claims).toMatchObject({ sub: "key-123", iss: "cdp", uris: ["POST api.cdp.coinbase.com/platform/v2/x402/settle"], exp: 1_800_000_120 });
    const ok = await crypto.subtle.verify({ name: "Ed25519" }, pair.publicKey, fromB64url(s!), new TextEncoder().encode(`${h}.${c}`));
    expect(ok).toBe(true);
  });
  it("rejects a non-Ed25519 secret with a clear message", async () => {
    await expect(cdpJwt("k", btoa("short"), "GET", "https://api.cdp.coinbase.com/platform/v2/x402/supported")).rejects.toThrow(/Ed25519/);
  });
});
