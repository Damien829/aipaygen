# AIPayGen Facilitator: plan to become a main x402 payment network

## The position
In x402, every payment goes through a **facilitator**:
1. **Verify:** check the agent's signed USDC authorization.
2. **Settle:** submit it on-chain and pay the gas.
3. **Supported:** say which schemes and networks it handles.

That's the Visa-like seat: it touches every transaction it handles, and the money moves **directly from payer to merchant** (EIP-3009 `transferWithAuthorization`). The facilitator never holds funds.

## Market (research, 2026-11-03)
- Main facilitators: **Coinbase CDP**, **Dexter** and **PayAI**. Shares shift month to month.
  - Coinbase's estimated share ranges from roughly 25% to over 50% of transactions depending on date and metric.
  - Dexter has led daily counts at times, and on Solana.
  - PayAI is strong on Solana.
- x402 is reported at around $600M annualized volume in early 2026, though daily transactions swing widely (peak about 731k/day in Dec 2025, about 57k/day in Feb 2026).
- Sources are mostly crypto media and vendor blogs, and they conflict; check Dune and x402scan dashboards before quoting numbers.
- Coinbase's facilitator is free for merchants, so **price can't be the only lever.**

## How we win (differentiation)
1. **Settlement plus distribution:** merchants that settle through us are automatically listed, verified and ranked in the AIPayGen marketplace (11k+ listings, A2A agent, MCP). Agents find them, and payments flow through us. No other facilitator bundles demand.
2. **Merchant analytics:** who pays you, which agents, which tools, how much. Coinbase gives you a transaction hash; we give you a dashboard.
3. **Trust layer:** we already test-call services. Settlement history adds a "paid and delivered" reliability signal for merchants.
4. **Neutral and multi-chain:** Base first, then Solana and other EVM chains.
5. **Speed of integration:** one URL change (`FACILITATOR_URL=https://aipaygen.com/facilitator`).

## Revenue model (phased)
- **Phase A (now):** free, to build volume. Gas on Base is a fraction of a cent per settlement, which we absorb, capped by per-key rate limits.
- **Phase B:** paid tiers for merchants, a flat monthly plan or per-settlement billing on volume above a free allowance, billed separately (Stripe or x402). The payment itself stays merchant-direct.
- **Phase C:** value-added schemes: `upto` (pay for actual usage), `batch-settlement` (many micro-payments, one transaction, much cheaper), and analytics or premium listing.
- Fees are never deducted from the payment: x402 transfers go payer to merchant in full.

## Legal (not legal advice)
- Non-custodial "software that submits a signed transfer" is the lowest-risk design, and that's what this is.
- Commentary suggests facilitators that **hold** funds, use omnibus wallets or convert fiat may be money transmitters. We do none of those.
- GENIUS Act rules for stablecoins were still being finalized through 2026, and commenters asked Treasury to exclude non-custodial infrastructure. Watch the final rules.
- **Before charging fees: one hour with a fintech lawyer.** Also screen payers and merchants against OFAC sanctions lists, since settling for a sanctioned address is a risk even when non-custodial.

## Build (this repo)
- `src/facilitator.ts`: built on the official `x402Facilitator` and `registerExactEvmScheme` (`@x402/core` and `@x402/evm` 2.29). Endpoints:
  - `GET /facilitator/supported`
  - `POST /facilitator/verify`
  - `POST /facilitator/settle`
- **Settlement wallet:** a dedicated key in a Worker secret (`FACILITATOR_PRIVATE_KEY`). It holds only a little ETH for gas and **never** holds customer funds. Watch its balance.
- **Access:** verify is open. Settle needs an `apg_` key (abuse and gas control, plus per-merchant analytics) and is rate limited. Every settlement is recorded in D1.
- **Rollout:** Base Sepolia (testnet) → AIPayGen's own payments on mainnet → invited merchants → public.

## Owner actions
1. Create a fresh wallet for the facilitator (never reuse the payout wallet). Fund it with a little Base Sepolia ETH (free faucet) for testing, then about $5–10 of ETH on Base mainnet.
2. `npx wrangler secret put FACILITATOR_PRIVATE_KEY`.
3. Legal check before Phase B.
4. Submit to x402 ecosystem lists as a facilitator once mainnet is live.
