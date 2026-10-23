// End-to-end x402 test: pays for one AIPayGen tool call the way an AI agent would.
// TESTNET ONLY (Base Sepolia). Reads throwaway wallet keys from .secrets.local.
//
//   node scripts/x402-pay-test.mjs [url]
//
import { readFileSync } from "node:fs";
import { wrapFetchWithPaymentFromConfig } from "@x402/fetch";
import { ExactEvmScheme } from "@x402/evm";
import { decodePaymentResponseHeader } from "@x402/core/http";
import { createPublicClient, formatUnits, http, parseAbi } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";

const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"; // USDC on Base Sepolia
const url = process.argv[2] ?? "https://aipaygen.com/v1/dns_lookup?domain=anthropic.com";

const secrets = Object.fromEntries(
  readFileSync(new URL("../.secrets.local", import.meta.url), "utf8")
    .split("\n")
    .filter((l) => /^[A-Z_]+=/.test(l))
    .map((l) => l.split("=", 2)),
);
if (!secrets.TEST_PAYER_KEY) throw new Error("TEST_PAYER_KEY missing from .secrets.local");

const account = privateKeyToAccount(secrets.TEST_PAYER_KEY);
const chain = createPublicClient({ chain: baseSepolia, transport: http() });
const balance = (addr) =>
  chain.readContract({ address: USDC, abi: parseAbi(["function balanceOf(address) view returns (uint256)"]), functionName: "balanceOf", args: [addr] });

const before = await balance(account.address);
console.log(`Payer ${account.address}`);
console.log(`Payer balance: ${formatUnits(before, 6)} test USDC`);
if (before === 0n) {
  console.log("\nThe payer has no test USDC yet. Get free test USDC at https://faucet.circle.com (network: Base Sepolia) for the address above.");
  process.exit(1);
}

const payingFetch = wrapFetchWithPaymentFromConfig(fetch, {
  schemes: [{ network: "eip155:84532", client: new ExactEvmScheme(account) }],
});

console.log(`\nCalling ${url} with no API key...`);
const res = await payingFetch(url);
const body = await res.json();
console.log(`HTTP ${res.status}`);

const receipt = res.headers.get("payment-response");
if (receipt) {
  const r = decodePaymentResponseHeader(receipt);
  console.log(`Paid. Transaction ${r.transaction} on ${r.network}`);
  console.log(`https://sepolia.basescan.org/tx/${r.transaction}`);
}
console.log("\nResult:", JSON.stringify(body.data ?? body, null, 2).slice(0, 800));

const after = await balance(account.address);
console.log(`\nPayer balance after: ${formatUnits(after, 6)} test USDC (spent ${formatUnits(before - after, 6)})`);
process.exit(res.ok && receipt ? 0 : 1);
