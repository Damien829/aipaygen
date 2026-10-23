// Debug helper: builds an x402 payment for a live endpoint and asks the facilitator to verify it,
// printing the full response. TESTNET ONLY.
import { readFileSync } from "node:fs";
import { x402Client } from "@x402/core/client";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { decodePaymentRequiredHeader } from "@x402/core/http";
import { ExactEvmScheme } from "@x402/evm";
import { privateKeyToAccount } from "viem/accounts";

const secrets = Object.fromEntries(readFileSync(new URL("../.secrets.local", import.meta.url), "utf8").split("\n").filter((l) => /^[A-Z_]+=/.test(l)).map((l) => l.split("=", 2)));
const account = privateKeyToAccount(secrets.TEST_PAYER_KEY);
const url = process.argv[2] ?? "https://aipaygen.com/v1/dns_lookup?domain=anthropic.com";

const res = await fetch(url);
const pr = decodePaymentRequiredHeader(res.headers.get("payment-required"));
const client = new x402Client().register("eip155:84532", new ExactEvmScheme(account));
const payload = await client.createPaymentPayload(pr);
console.log("payload:", JSON.stringify(payload, null, 2).slice(0, 1500));
const fac = new HTTPFacilitatorClient({ url: process.env.FACILITATOR_URL ?? "https://x402.org/facilitator" });
const vr = await fac.verify(payload, pr.accepts[0]);
console.log("verify:", JSON.stringify(vr, null, 2));
if (process.argv.includes("--settle")) {
  const sr = await fac.settle(payload, pr.accepts[0]);
  console.log("settle:", JSON.stringify(sr, null, 2));
}
