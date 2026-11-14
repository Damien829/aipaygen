import { z } from "zod";
import { fetchJson } from "../lib/net";
import { ToolError } from "../lib/errors";
import { defineTool } from "./types";

/**
 * Crypto market and on-chain data from free, keyless sources: CoinGecko and
 * Coinbase prices, Alternative.me fear & greed, GoPlus token security,
 * DexScreener pairs, and public EVM RPC nodes.
 */

const USER_AGENT = "AIPayGenBot/2.0 (+https://aipaygen.com/bot)";
const ADDRESS = /^0x[0-9a-fA-F]{40}$/;

export interface Chain { id: number; name: string; rpc: string; native: string; usdc: { address: string; decimals: number } }
export const CHAINS: Record<string, Chain> = {
  ethereum: { id: 1, name: "Ethereum", rpc: "https://ethereum-rpc.publicnode.com", native: "ETH", usdc: { address: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", decimals: 6 } },
  base: { id: 8453, name: "Base", rpc: "https://mainnet.base.org", native: "ETH", usdc: { address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", decimals: 6 } },
  arbitrum: { id: 42161, name: "Arbitrum One", rpc: "https://arb1.arbitrum.io/rpc", native: "ETH", usdc: { address: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", decimals: 6 } },
  optimism: { id: 10, name: "OP Mainnet", rpc: "https://mainnet.optimism.io", native: "ETH", usdc: { address: "0x0b2C639c533813f4Aa9D7837cAf62653d097Ff85", decimals: 6 } },
  polygon: { id: 137, name: "Polygon", rpc: "https://polygon-bor-rpc.publicnode.com", native: "POL", usdc: { address: "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", decimals: 6 } },
  bsc: { id: 56, name: "BNB Smart Chain", rpc: "https://bsc-dataseed.bnbchain.org", native: "BNB", usdc: { address: "0x8AC76a51cc950d9822D68b83fE1Ad5d8bdCAfC5d", decimals: 18 } },
  avalanche: { id: 43114, name: "Avalanche C-Chain", rpc: "https://api.avax.network/ext/bc/C/rpc", native: "AVAX", usdc: { address: "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E", decimals: 6 } },
};
const CHAIN_ALIASES: Record<string, string> = { eth: "ethereum", mainnet: "ethereum", arb: "arbitrum", op: "optimism", matic: "polygon", bnb: "bsc", avax: "avalanche" };
const CHAIN_NAMES = Object.keys(CHAINS);

export function chainOf(input: string): Chain & { key: string } {
  const k = input.trim().toLowerCase();
  const key = CHAINS[k] ? k : CHAIN_ALIASES[k] ?? Object.keys(CHAINS).find((c) => String(CHAINS[c]!.id) === k);
  if (!key || !CHAINS[key]) throw new ToolError(`Unknown chain "${input}". Use one of: ${CHAIN_NAMES.join(", ")}.`, "INVALID_INPUT", 400);
  return { key, ...CHAINS[key]! };
}

/** Formats an integer amount with `decimals` places, trimmed: 1234500n, 6 -> "1.2345". */
export function formatUnits(value: bigint, decimals: number): string {
  const neg = value < 0n;
  const v = neg ? -value : value;
  const base = 10n ** BigInt(decimals);
  const whole = v / base;
  const frac = (v % base).toString().padStart(decimals, "0").replace(/0+$/, "");
  return `${neg ? "-" : ""}${whole}${frac ? `.${frac}` : ""}`;
}

async function rpc<T>(chain: Chain, method: string, params: unknown[]): Promise<T> {
  let res: Response;
  try {
    res = await fetch(chain.rpc, {
      method: "POST",
      headers: { "content-type": "application/json", "user-agent": USER_AGENT },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
      signal: AbortSignal.timeout(8000),
    });
  } catch {
    throw new ToolError(`The ${chain.name} node is unreachable right now.`, "UPSTREAM_UNREACHABLE", 502);
  }
  const body = (await res.json().catch(() => null)) as { result?: T; error?: { message?: string } } | null;
  if (!body || body.error || body.result === undefined) throw new ToolError(`The ${chain.name} node returned an error${body?.error?.message ? `: ${body.error.message}` : ""}.`, "UPSTREAM_ERROR", 502);
  return body.result;
}

const balanceOfData = (addr: string) => `0x70a08231${addr.slice(2).toLowerCase().padStart(64, "0")}`;

// ---------- prices ----------

interface CgSearch { coins?: { id: string; symbol: string; name: string; market_cap_rank: number | null }[] }
type CgPrice = Record<string, { usd?: number; usd_market_cap?: number; usd_24h_vol?: number; usd_24h_change?: number; last_updated_at?: number }>;

const COMMON: Record<string, string> = {
  btc: "bitcoin", bitcoin: "bitcoin", eth: "ethereum", ether: "ethereum", ethereum: "ethereum", sol: "solana", solana: "solana", usdc: "usd-coin",
  usdt: "tether", bnb: "binancecoin", xrp: "ripple", ada: "cardano", doge: "dogecoin", trx: "tron", avax: "avalanche-2", link: "chainlink",
  dot: "polkadot", matic: "matic-network", pol: "polygon-ecosystem-token", ltc: "litecoin", shib: "shiba-inu", ton: "the-open-network", sui: "sui", pepe: "pepe",
};

async function coinIds(symbols: string[]): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  for (const s of symbols) {
    const k = s.trim().toLowerCase();
    if (COMMON[k]) {
      out.set(s, COMMON[k]!);
      continue;
    }
    const { data } = await fetchJson<CgSearch>(`https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(k)}`, { timeoutMs: 6000 });
    const coins = data?.coins ?? [];
    // Prefer an exact symbol or id match with the best market-cap rank; tickers are not unique.
    const exact = coins.filter((c) => c.symbol.toLowerCase() === k || c.id === k).sort((a, b) => (a.market_cap_rank ?? 1e9) - (b.market_cap_rank ?? 1e9));
    const pick = exact[0] ?? coins[0];
    if (pick) out.set(s, pick.id);
  }
  return out;
}

export const cryptoPrice = defineTool({
  name: "crypto_price",
  title: "Crypto prices",
  description:
    "Live USD price, 24h change, market cap and volume for any cryptocurrency by ticker or name (BTC, ETH, SOL, PEPE... 15,000+ coins), plus the market-wide Fear & Greed index.",
  priceMicro: 1000,
  cacheTtl: 60,
  input: z.object({
    coins: z.array(z.string().min(1).max(60)).min(1).max(20).describe('Tickers or names, e.g. ["BTC", "ETH", "solana"].'),
  }),
  example: { coins: ["BTC", "ETH", "SOL"] },
  async run({ coins }) {
    const ids = await coinIds(coins);
    const unique = [...new Set(ids.values())];
    const [prices, fng] = await Promise.all([
      unique.length
        ? fetchJson<CgPrice>(
            `https://api.coingecko.com/api/v3/simple/price?ids=${unique.join(",")}&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true&include_last_updated_at=true`,
            { timeoutMs: 6000 },
          )
        : Promise.resolve({ status: 200, data: {} as CgPrice }),
      fetchJson<{ data?: { value: string; value_classification: string }[] }>("https://api.alternative.me/fng/?limit=1", { timeoutMs: 4000 }).catch(() => ({ data: null })),
    ]);
    const results = await Promise.all(
      coins.map(async (c) => {
        const id = ids.get(c);
        const p = id ? prices.data?.[id] : undefined;
        if (p?.usd !== undefined) {
          return {
            query: c, id, price_usd: p.usd,
            change_24h_pct: p.usd_24h_change === undefined ? null : Math.round(p.usd_24h_change * 100) / 100,
            market_cap_usd: p.usd_market_cap ? Math.round(p.usd_market_cap) : null,
            volume_24h_usd: p.usd_24h_vol ? Math.round(p.usd_24h_vol) : null,
            updated: p.last_updated_at ? new Date(p.last_updated_at * 1000).toISOString() : null,
            source: "CoinGecko",
          };
        }
        // Fallback for big tickers when CoinGecko is rate-limited.
        const { data } = await fetchJson<{ data?: { amount: string } }>(`https://api.coinbase.com/v2/prices/${encodeURIComponent(c.trim().toUpperCase())}-USD/spot`, { timeoutMs: 4000 }).catch(() => ({ data: null }));
        if (data?.data?.amount) return { query: c, id: id ?? null, price_usd: Number(data.data.amount), change_24h_pct: null, market_cap_usd: null, volume_24h_usd: null, updated: new Date().toISOString(), source: "Coinbase" };
        return { query: c, id: id ?? null, price_usd: null, error: "Coin not found" };
      }),
    );
    if (results.every((r) => r.price_usd === null)) throw new ToolError("None of those coins were found. Try tickers like BTC or full names like solana.", "NOT_FOUND", 404);
    const f = fng.data?.data?.[0];
    return {
      prices: results,
      fear_greed: f ? { value: Number(f.value), label: f.value_classification } : null,
      credit: "Prices: CoinGecko (Coinbase fallback). Fear & Greed: Alternative.me.",
    };
  },
});

// ---------- token security ----------

type GoPlus = Record<string, string | number | null | unknown[] | undefined>;
const flag = (v: unknown) => v === "1";
const pct = (v: unknown) => (typeof v === "string" && v !== "" ? Math.round(Number(v) * 10_000) / 100 : null);

/** Plain-English risks from a GoPlus token_security record, worst first, plus a 0-100 risk score. */
export function tokenRisks(r: GoPlus) {
  const risks: { level: "critical" | "high" | "medium"; issue: string }[] = [];
  if (flag(r.is_honeypot)) risks.push({ level: "critical", issue: "Honeypot: holders can't sell." });
  if (flag(r.cannot_sell_all)) risks.push({ level: "critical", issue: "Holders can't sell their full balance." });
  if (flag(r.cannot_buy)) risks.push({ level: "high", issue: "Token can't be bought." });
  const sell = pct(r.sell_tax), buy = pct(r.buy_tax);
  if (sell !== null && sell >= 10) risks.push({ level: sell >= 50 ? "critical" : "high", issue: `Sell tax is ${sell}%.` });
  if (buy !== null && buy >= 10) risks.push({ level: "high", issue: `Buy tax is ${buy}%.` });
  if (flag(r.hidden_owner)) risks.push({ level: "high", issue: "Has a hidden owner." });
  if (flag(r.can_take_back_ownership)) risks.push({ level: "high", issue: "Ownership can be taken back after renouncing." });
  if (flag(r.owner_change_balance)) risks.push({ level: "high", issue: "Owner can change holders' balances." });
  if (flag(r.selfdestruct)) risks.push({ level: "high", issue: "Contract can self-destruct." });
  if (flag(r.is_blacklisted)) risks.push({ level: "medium", issue: "Has a blacklist (addresses can be blocked)." });
  if (flag(r.is_mintable)) risks.push({ level: "medium", issue: "Supply can be minted." });
  if (flag(r.transfer_pausable)) risks.push({ level: "medium", issue: "Transfers can be paused." });
  if (flag(r.slippage_modifiable)) risks.push({ level: "medium", issue: "Taxes can be changed by the owner." });
  if (r.is_open_source === "0") risks.push({ level: "high", issue: "Contract source is not verified." });
  if (flag(r.is_proxy)) risks.push({ level: "medium", issue: "Upgradeable proxy: code can change." });
  if (flag(r.honeypot_with_same_creator)) risks.push({ level: "high", issue: "Creator has deployed honeypots before." });
  const weight = { critical: 60, high: 25, medium: 8 };
  const score = Math.min(100, risks.reduce((s, x) => s + weight[x.level], 0));
  return { risks, score, verdict: score >= 60 ? "dangerous" : score >= 25 ? "risky" : risks.length ? "caution" : "no red flags" };
}

export const tokenSecurity = defineTool({
  name: "token_security",
  title: "Token security scan (honeypot check)",
  description:
    "Check an ERC-20 token contract for scams before buying: honeypot, buy/sell taxes, mint and blacklist powers, hidden owner, proxy upgrades, unverified code, holder concentration. Returns a risk score and plain-English red flags. Ethereum, Base, BNB, Arbitrum, Polygon, Optimism, Avalanche.",
  priceMicro: 3000,
  cacheTtl: 600,
  input: z.object({
    chain: z.string().min(2).max(20).describe(`Chain: ${CHAIN_NAMES.join(", ")}.`),
    address: z.string().regex(ADDRESS).describe("Token contract address (0x...)."),
  }),
  example: { chain: "base", address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913" },
  async run({ chain, address }) {
    const c = chainOf(chain);
    const { status, data } = await fetchJson<{ code: number; message: string; result?: Record<string, GoPlus> }>(
      `https://api.gopluslabs.io/api/v1/token_security/${c.id}?contract_addresses=${address.toLowerCase()}`,
      { timeoutMs: 10_000 },
    );
    if (!data) throw new ToolError(`The token security service didn't answer (status ${status}).`, "UPSTREAM_ERROR", 502);
    const r = data.result?.[address.toLowerCase()];
    if (!r || !Object.keys(r).length) throw new ToolError(`No token found at ${address} on ${c.name}.`, "NOT_FOUND", 404);
    const holders = Array.isArray(r.holders) ? (r.holders as { address: string; percent: string; is_contract?: number; tag?: string }[]) : [];
    const top10 = holders.slice(0, 10).reduce((s, h) => s + Number(h.percent || 0), 0);
    const { risks, score, verdict } = tokenRisks(r);
    if (top10 > 0.7 && !holders.some((h) => /lock|burn|dead/i.test(h.tag ?? ""))) risks.push({ level: "medium", issue: `Top 10 holders own ${Math.round(top10 * 100)}% of supply.` });
    return {
      chain: c.key, address,
      name: r.token_name ?? null, symbol: r.token_symbol ?? null,
      verdict, risk_score: score, risks,
      buy_tax_pct: pct(r.buy_tax), sell_tax_pct: pct(r.sell_tax),
      verified_source: r.is_open_source === "1", honeypot: flag(r.is_honeypot), mintable: flag(r.is_mintable), proxy: flag(r.is_proxy),
      holders: r.holder_count ? Number(r.holder_count) : null, top10_holders_pct: holders.length ? Math.round(top10 * 10_000) / 100 : null,
      owner: (r.owner_address as string) || null, creator: (r.creator_address as string) || null,
      on_major_exchange: flag(r.is_in_cex as unknown), trusted_list: flag(r.trust_list),
      credit: "Security data: GoPlus Security. Not financial advice.",
    };
  },
});

// ---------- DEX data ----------

interface DexPair {
  chainId: string; dexId: string; url: string; pairAddress: string; priceUsd?: string; fdv?: number; marketCap?: number; pairCreatedAt?: number;
  baseToken: { address: string; name: string; symbol: string }; quoteToken: { symbol: string };
  liquidity?: { usd?: number }; volume?: { h24?: number; h1?: number }; priceChange?: { h1?: number; h24?: number }; txns?: { h24?: { buys: number; sells: number } };
}

export function pairSummary(p: DexPair) {
  return {
    chain: p.chainId, dex: p.dexId, pair: `${p.baseToken.symbol}/${p.quoteToken.symbol}`,
    token: { name: p.baseToken.name, symbol: p.baseToken.symbol, address: p.baseToken.address },
    price_usd: p.priceUsd ? Number(p.priceUsd) : null,
    liquidity_usd: p.liquidity?.usd ? Math.round(p.liquidity.usd) : null,
    volume_24h_usd: p.volume?.h24 ? Math.round(p.volume.h24) : null,
    change_1h_pct: p.priceChange?.h1 ?? null, change_24h_pct: p.priceChange?.h24 ?? null,
    buys_24h: p.txns?.h24?.buys ?? null, sells_24h: p.txns?.h24?.sells ?? null,
    market_cap_usd: p.marketCap ?? p.fdv ?? null,
    pair_age_days: p.pairCreatedAt ? Math.floor((Date.now() - p.pairCreatedAt) / 86_400_000) : null,
    url: p.url,
  };
}

export const dexToken = defineTool({
  name: "dex_token",
  title: "DEX token and pair data",
  description:
    "Live on-chain market data for any token on 80+ chains and DEXes (Uniswap, Raydium, PancakeSwap, Aerodrome...): price, liquidity, 24h volume, buys vs sells, market cap and pair age. Search by name/ticker or look up a contract address.",
  priceMicro: 1000,
  cacheTtl: 60,
  input: z.object({
    query: z.string().max(100).optional().describe('Token name or ticker, e.g. "PEPE". Use this or address.'),
    address: z.string().max(100).optional().describe("Token contract address (EVM 0x... or Solana mint)."),
    chain: z.string().max(30).optional().describe('Chain to look on with an address, e.g. "base", "ethereum", "solana", "bsc". Default: all.'),
    limit: z.number().int().min(1).max(20).optional().describe("Number of pairs. Default 5, most liquid first."),
  }),
  example: { query: "PEPE", limit: 3 },
  async run({ query, address, chain, limit }) {
    let pairs: DexPair[] = [];
    if (address?.trim()) {
      const a = address.trim();
      if (!/^(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})$/.test(a)) throw new ToolError("That doesn't look like a token address.", "INVALID_INPUT", 400);
      const { data } = await fetchJson<{ pairs?: DexPair[] | null }>(`https://api.dexscreener.com/latest/dex/tokens/${a}`, { timeoutMs: 8000 });
      pairs = data?.pairs ?? [];
      // Pairs where the token is the quote side (e.g. USDC in AERO/USDC) describe the other token; prefer pairs that price this one.
      const own = pairs.filter((p) => p.baseToken.address.toLowerCase() === a.toLowerCase());
      if (own.length) pairs = own;
      if (chain) {
        const want = chain.trim().toLowerCase();
        pairs = pairs.filter((p) => p.chainId === want || p.chainId === (CHAIN_ALIASES[want] ?? want));
      }
    } else if (query?.trim()) {
      const { data } = await fetchJson<{ pairs?: DexPair[] | null }>(`https://api.dexscreener.com/latest/dex/search?q=${encodeURIComponent(query.trim())}`, { timeoutMs: 8000 });
      pairs = data?.pairs ?? [];
    } else throw new ToolError("Pass a query (name or ticker) or a token address.", "INVALID_INPUT", 400);
    if (!pairs.length) throw new ToolError("No trading pairs found.", "NOT_FOUND", 404);
    pairs.sort((a, b) => (b.liquidity?.usd ?? 0) - (a.liquidity?.usd ?? 0));
    return { count: pairs.length, pairs: pairs.slice(0, limit ?? 5).map(pairSummary), credit: "Market data: DexScreener." };
  },
});

// ---------- wallet and gas ----------

export const walletBalance = defineTool({
  name: "wallet_balance",
  title: "Wallet balances (EVM)",
  description:
    "Native coin and USDC balance of any wallet address on Ethereum, Base, Arbitrum, Optimism, Polygon, BNB Chain and Avalanche at once, plus any extra ERC-20 token you name. Read straight from the chains.",
  priceMicro: 1000,
  cacheTtl: 30,
  input: z.object({
    address: z.string().regex(ADDRESS).describe("Wallet address (0x...)."),
    chains: z.array(z.string()).max(7).optional().describe(`Chains to check. Default: all (${CHAIN_NAMES.join(", ")}).`),
    token: z.string().regex(ADDRESS).optional().describe("Optional extra ERC-20 token contract to check (on the first chain listed)."),
  }),
  example: { address: "0xebA22e8CD05Cb72A2F913099D6cCA666DD6D35B0", chains: ["base", "ethereum"] },
  async run({ address, chains, token }) {
    const list = (chains?.length ? chains : CHAIN_NAMES).map(chainOf);
    const balances = await Promise.all(
      list.map(async (c) => {
        try {
          const [nat, usdc] = await Promise.all([
            rpc<string>(c, "eth_getBalance", [address, "latest"]),
            rpc<string>(c, "eth_call", [{ to: c.usdc.address, data: balanceOfData(address) }, "latest"]),
          ]);
          return { chain: c.key, native_symbol: c.native, native: formatUnits(BigInt(nat), 18), usdc: formatUnits(BigInt(usdc === "0x" ? "0x0" : usdc), c.usdc.decimals) };
        } catch (err) {
          return { chain: c.key, error: err instanceof Error ? err.message : "unavailable" };
        }
      }),
    );
    let extra: Record<string, unknown> | null = null;
    if (token) {
      const c = list[0]!;
      try {
        const [bal, dec, sym] = await Promise.all([
          rpc<string>(c, "eth_call", [{ to: token, data: balanceOfData(address) }, "latest"]),
          rpc<string>(c, "eth_call", [{ to: token, data: "0x313ce567" }, "latest"]),
          rpc<string>(c, "eth_call", [{ to: token, data: "0x95d89b41" }, "latest"]),
        ]);
        const decimals = Number(BigInt(dec === "0x" ? "0x12" : dec));
        extra = { chain: c.key, token, symbol: decodeAbiString(sym), balance: formatUnits(BigInt(bal === "0x" ? "0x0" : bal), decimals) };
      } catch (err) {
        extra = { chain: c.key, token, error: err instanceof Error ? err.message : "unavailable" };
      }
    }
    return { address, balances, token: extra };
  },
});

/** Decodes an ABI-encoded `string` return value (falls back to bytes32 symbols). */
export function decodeAbiString(hex: string): string | null {
  const h = hex.replace(/^0x/, "");
  if (!h) return null;
  try {
    const bytes = (s: string) => new TextDecoder().decode(new Uint8Array(s.match(/../g)!.map((b) => parseInt(b, 16)))).replace(/\0+$/, "");
    if (h.length === 64) return bytes(h) || null;
    const len = parseInt(h.slice(64, 128), 16);
    return bytes(h.slice(128, 128 + len * 2)) || null;
  } catch {
    return null;
  }
}

export const gasPrice = defineTool({
  name: "gas_price",
  title: "Gas prices across chains",
  description:
    "Current gas price on Ethereum, Base, Arbitrum, Optimism, Polygon, BNB Chain and Avalanche, in gwei, with the latest block number. Use it to pick the cheapest chain or time a transaction.",
  priceMicro: 1000,
  cacheTtl: 15,
  input: z.object({ chains: z.array(z.string()).max(7).optional().describe(`Chains. Default: all (${CHAIN_NAMES.join(", ")}).`) }),
  example: { chains: ["ethereum", "base", "arbitrum"] },
  async run({ chains }) {
    const list = (chains?.length ? chains : CHAIN_NAMES).map(chainOf);
    const out = await Promise.all(
      list.map(async (c) => {
        try {
          const [gp, bn] = await Promise.all([rpc<string>(c, "eth_gasPrice", []), rpc<string>(c, "eth_blockNumber", [])]);
          const gwei = Number(BigInt(gp)) / 1e9;
          return { chain: c.key, gas_gwei: gwei < 0.01 ? Number(gwei.toPrecision(3)) : Math.round(gwei * 1000) / 1000, block: Number(BigInt(bn)), native_symbol: c.native };
        } catch (err) {
          return { chain: c.key, error: err instanceof Error ? err.message : "unavailable" };
        }
      }),
    );
    return { chains: out, checked_at: new Date().toISOString() };
  },
});
