// End-to-end test of prepaid credits bought with x402 (POST /v1/topup).
// Creates a fresh API key (optionally with a referral code), pays the 402 from the
// test payer in .secrets.local, and checks the key's balance went up. Spends REAL USDC.
//
//   node scripts/x402-topup-test.mjs <amount_usd> [ref_code]
//
// The new key is never printed in full (only its prefix).
import { appendFileSync, readFileSync } from "node:fs";
import { wrapFetchWithPaymentFromConfig } from "@x402/fetch";
import { ExactEvmScheme } from "@x402/evm";
import { decodePaymentResponseHeader } from "@x402/core/http";
import { privateKeyToAccount } from "viem/accounts";

const BASE = process.env.AIPAYGEN_URL ?? "https://aipaygen.com";
const amount = Number(process.argv[2]);
const ref = process.argv[3];
if (!Number.isFinite(amount) || amount < 1 || amount > 100) throw new Error("usage: x402-topup-test.mjs <amount_usd 1-100> [ref_code]");

const secrets = Object.fromEntries(
  readFileSync(new URL("../.secrets.local", import.meta.url), "utf8").split("\n").filter((l) => /^[A-Z_]+=/.test(l)).map((l) => l.split("=", 2)),
);
const account = privateKeyToAccount(secrets.TEST_PAYER_KEY);

// Reuse TEST_API_KEY from .secrets.local when there's no ref to test (new keys are limited per IP per day);
// a ref test needs a brand-new key, since referral links are set at creation.
let key = ref ? undefined : secrets.TEST_API_KEY;
if (!key) {
  const created = await (await fetch(`${BASE}/v1/keys`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ label: "topup e2e test", ...(ref ? { ref } : {}) }),
  })).json();
  key = created.api_key;
  if (!key) throw new Error(`Key creation failed: ${JSON.stringify(created)}`);
  if (!ref) appendFileSync(new URL("../.secrets.local", import.meta.url), `TEST_API_KEY=${key}\n`); // gitignored
}
const auth = { authorization: `Bearer ${key}` };
const balance = async () => (await (await fetch(`${BASE}/v1/balance`, { headers: auth })).json()).balance;
console.log(`Key ${key.slice(0, 10)}…${ref ? ` (new, ref ${ref})` : ""}; balance ${await balance()}`);

const payingFetch = wrapFetchWithPaymentFromConfig(fetch, { schemes: [{ network: "eip155:8453", client: new ExactEvmScheme(account) }] });
const res = await payingFetch(`${BASE}/v1/topup`, {
  method: "POST",
  headers: { "content-type": "application/json", ...auth },
  body: JSON.stringify({ amount_usd: amount }),
});
const body = await res.json();
console.log(`Top-up HTTP ${res.status}`);
const receipt = res.headers.get("payment-response");
if (receipt) {
  const r = decodePaymentResponseHeader(receipt);
  console.log(`Paid. Transaction ${r.transaction} on ${r.network}`);
}
console.log("Response:", JSON.stringify(body));
console.log(`Balance after: ${await balance()}`);
