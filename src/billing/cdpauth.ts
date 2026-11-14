/**
 * Auth for Coinbase's CDP x402 facilitator: a short-lived EdDSA JWT per request,
 * signed with the CDP Secret API key (Ed25519, the portal's default).
 * Settling through CDP is what lists our tools in the CDP Bazaar and Agentic.Market.
 *
 * Secrets (never in git): CDP_API_KEY_ID, CDP_API_KEY_SECRET (base64, 64 bytes: seed + public key).
 */

export const CDP_FACILITATOR = "https://api.cdp.coinbase.com/platform/v2/x402";

const b64url = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64urlText = (s: string) => b64url(new TextEncoder().encode(s));

function decodeSecret(secret: string): Uint8Array {
  const raw = Uint8Array.from(atob(secret.trim()), (c) => c.charCodeAt(0));
  if (raw.length !== 64) throw new Error("CDP_API_KEY_SECRET must be an Ed25519 key (base64 of 64 bytes). Create the key with the Ed25519 algorithm.");
  return raw;
}

const keyCache = new Map<string, Promise<CryptoKey>>();

function signingKey(secret: string): Promise<CryptoKey> {
  let k = keyCache.get(secret);
  if (!k) {
    const raw = decodeSecret(secret);
    const jwk = { kty: "OKP", crv: "Ed25519", d: b64url(raw.slice(0, 32)), x: b64url(raw.slice(32)) };
    k = crypto.subtle.importKey("jwk", jwk, { name: "Ed25519" }, false, ["sign"]);
    keyCache.set(secret, k);
  }
  return k;
}

/** One JWT for one request ("POST api.cdp.coinbase.com/platform/v2/x402/settle"), valid two minutes. */
export async function cdpJwt(keyId: string, secret: string, method: string, url: string, now = Date.now()): Promise<string> {
  const u = new URL(url);
  const iat = Math.floor(now / 1000);
  const nonce = [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const header = { alg: "EdDSA", kid: keyId, typ: "JWT", nonce };
  const claims = { sub: keyId, iss: "cdp", nbf: iat, iat, exp: iat + 120, uris: [`${method} ${u.host}${u.pathname}`] };
  const input = `${b64urlText(JSON.stringify(header))}.${b64urlText(JSON.stringify(claims))}`;
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, await signingKey(secret), new TextEncoder().encode(input)));
  return `${input}.${b64url(sig)}`;
}

/** Headers for HTTPFacilitatorClient's createAuthHeaders: one fresh JWT per path. */
export async function cdpAuthHeaders(keyId: string, secret: string) {
  const h = async (method: string, path: string) => ({ Authorization: `Bearer ${await cdpJwt(keyId, secret, method, `${CDP_FACILITATOR}/${path}`)}` });
  const [verify, settle, supported] = await Promise.all([h("POST", "verify"), h("POST", "settle"), h("GET", "supported")]);
  return { verify, settle, supported };
}
