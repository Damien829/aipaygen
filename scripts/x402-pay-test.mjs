// End-to-end x402 test: pays for one AIPayGen tool call the way an AI agent would.
// Uses the test payer wallet in .secrets.local. Base Sepolia by default;
// --mainnet spends REAL USDC on Base.
//
//   node scripts/x402-pay-test.mjs [--mainnet] [url]
//
import { readFileSync } from "node:fs";
import { wrapFetchWithPaymentFromConfig } from "@x402/fetch";
import { ExactEvmScheme } from "@x402/evm";
import { decodePaymentResponseHeader } from "@x402/core/http";
import { createPublicClient, formatUnits, http, parseAbi } from "viem";
import { base, baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";

const MAINNET = process.argv.includes("--mainnet");
const NET = MAINNET
  ? { chain: base, caip: "eip155:8453", usdc: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", explorer: "https://basescan.org", label: "USDC" }
  : { chain: baseSepolia, caip: "eip155:84532", usdc: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", explorer: "https://sepolia.basescan.org", label: "test USDC" };
const USDC = NET.usdc;
const url = process.argv.slice(2).find((a) => !a.startsWith("--")) ?? "https://aipaygen.com/v1/dns_lookup?domain=anthropic.com";

const secrets = Object.fromEntries(
  readFileSync(new URL("../.secrets.local", import.meta.url), "utf8")
    .split("\n")
    .filter((l) => /^[A-Z_]+=/.test(l))
    .map((l) => l.split("=", 2)),
);
if (!secrets.TEST_PAYER_KEY) throw new Error("TEST_PAYER_KEY missing from .secrets.local");

const account = privateKeyToAccount(secrets.TEST_PAYER_KEY);
const chain = createPublicClient({ chain: NET.chain, transport: http() });
const balance = (addr) =>
  chain.readContract({ address: USDC, abi: parseAbi(["function balanceOf(address) view returns (uint256)"]), functionName: "balanceOf", args: [addr] });

const before = await balance(account.address);
console.log(`Payer ${account.address}`);
console.log(`Payer balance: ${formatUnits(before, 6)} ${NET.label}`);
if (before === 0n) {
  const how = MAINNET ? "Send USDC on the Base network" : "Get free test USDC at https://faucet.circle.com (network: Base Sepolia)";
  console.log(`\nThe payer has no ${NET.label} yet. ${how} to the address above.`);
  process.exit(1);
}

const payingFetch = wrapFetchWithPaymentFromConfig(fetch, {
  schemes: [{ network: NET.caip, client: new ExactEvmScheme(account) }],
});

console.log(`\nCalling ${url} with no API key...`);
const res = await payingFetch(url);
const body = await res.json();
console.log(`HTTP ${res.status}`);

const receipt = res.headers.get("payment-response");
if (receipt) {
  const r = decodePaymentResponseHeader(receipt);
  console.log(`Paid. Transaction ${r.transaction} on ${r.network}`);
  console.log(`${NET.explorer}/tx/${r.transaction}`);
}
console.log("\nResult:", JSON.stringify(body.data ?? body, null, 2).slice(0, 800));

const after = await balance(account.address);
console.log(`\nPayer balance after: ${formatUnits(after, 6)} ${NET.label} (spent ${formatUnits(before - after, 6)})`);
process.exit(res.ok && receipt ? 0 : 1);
