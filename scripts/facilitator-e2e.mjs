// End-to-end test of the AIPayGen facilitator on Base Sepolia, the way a real
// resource server would use it: build requirements, have the payer sign, then
// /verify (no gas) and optionally /settle (moves real test USDC, our wallet pays gas).
//
//   node scripts/facilitator-e2e.mjs [base-url] [--settle apg_key]
//
// Reads TEST_PAYER_KEY and FACILITATOR_TEST_KEY from .secrets.local. Never prints keys.
import { readFileSync } from "node:fs";
import { ExactEvmScheme } from "@x402/evm";
import { createPublicClient, formatUnits, http, parseAbi } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { baseSepolia } from "viem/chains";

const args = process.argv.slice(2);
const base = (args.find((a) => a.startsWith("http")) ?? "http://localhost:8787").replace(/\/$/, "");
const settleKey = args.includes("--settle") ? args[args.indexOf("--settle") + 1] : null;
const sec = Object.fromEntries(readFileSync(new URL("../.secrets.local", import.meta.url), "utf8").split("\n")
  .filter((l) => l.includes("=") && !l.startsWith("#")).map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim()]));

const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"; // Base Sepolia
const payer = privateKeyToAccount(sec.TEST_PAYER_KEY);
const merchant = privateKeyToAccount(sec.FACILITATOR_TEST_KEY).address; // pay ourselves: the test only proves the flow
const chain = createPublicClient({ chain: baseSepolia, transport: http() });
// Sign with the chain's clock, not this machine's (a wrong local clock makes authorizations "expired").
const offsetMs = Number((await chain.getBlock()).timestamp) * 1000 - Date.now();
if (Math.abs(offsetMs) > 30_000) {
  console.log(`local clock is off by ${Math.round(offsetMs / 1000)}s; signing with chain time`);
  const realNow = Date.now;
  Date.now = () => realNow() + offsetMs;
}
const bal = (a) => chain.readContract({ address: USDC, abi: parseAbi(["function balanceOf(address) view returns (uint256)"]), functionName: "balanceOf", args: [a] });

const requirements = {
  scheme: "exact", network: "eip155:84532", asset: USDC, amount: "1000", payTo: merchant,
  maxTimeoutSeconds: 300, extra: { name: "USDC", version: "2" },
};

const supported = await (await fetch(`${base}/facilitator/supported`)).json();
console.log("supported:", JSON.stringify(supported.kinds), "signers:", JSON.stringify(supported.signers));

const partial = await new ExactEvmScheme(payer).createPaymentPayload(2, requirements);
const paymentPayload = { x402Version: 2, accepted: requirements, resource: { url: `${base}/e2e`, description: "facilitator e2e", mimeType: "application/json" }, ...partial };
const body = JSON.stringify({ x402Version: 2, paymentPayload, paymentRequirements: requirements });

const verify = await (await fetch(`${base}/facilitator/verify`, { method: "POST", headers: { "content-type": "application/json" }, body })).json();
console.log("verify:", JSON.stringify(verify));

if (settleKey) {
  const before = await bal(merchant);
  const r = await fetch(`${base}/facilitator/settle`, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${settleKey}` }, body });
  const settle = await r.json();
  console.log("settle:", r.status, JSON.stringify(settle));
  const after = await bal(merchant);
  console.log(`merchant USDC ${formatUnits(before, 6)} -> ${formatUnits(after, 6)}${settle.transaction ? `  https://sepolia.basescan.org/tx/${settle.transaction}` : ""}`);
}
