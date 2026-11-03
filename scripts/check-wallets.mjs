// Prints the address and Base Sepolia ETH / test USDC balance of each *_KEY in .secrets.local. Never prints keys.
//   node scripts/check-wallets.mjs
import { readFileSync } from "node:fs";
import { createPublicClient, formatEther, formatUnits, http, parseAbi } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
const sec = Object.fromEntries(readFileSync(new URL("../.secrets.local", import.meta.url), "utf8").split("\n").filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim()]));
const c = createPublicClient({ chain: baseSepolia, transport: http() });
const USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
for (const name of Object.keys(sec).filter((k) => /KEY$/.test(k) && /^0x[0-9a-fA-F]{64}$/.test(sec[k]))) {
  const a = privateKeyToAccount(sec[name]).address;
  const [eth, usdc] = await Promise.all([c.getBalance({ address: a }), c.readContract({ address: USDC, abi: parseAbi(["function balanceOf(address) view returns (uint256)"]), functionName: "balanceOf", args: [a] })]);
  console.log(`${name}: ${a} | Sepolia ETH ${formatEther(eth)} | test USDC ${formatUnits(usdc, 6)}`);
}
