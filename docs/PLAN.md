# AIPayGen plan

Shared by the two working sessions ("A" = facilitator, ingestion, health, find_tool, deploys of its own
work; "B" = tools, search ranking, discovery API, referrals). Updated 2026-11-14. Owner actions are marked
**You**. Rules: $0 hosting, prices stay hidden publicly, deploy only from a clean HEAD that contains the
other session's latest commit, and the owner approves each deploy, migration and spend.

## Where we are (2026-11-14, 13:30 UTC)

- 66 tools live (63 paid), every paid tool has settled a real payment through Coinbase CDP.
- 5 tools indexed in the CDP Bazaar so far (indexing lag after today's settlements).
- Catalog: 19,147 items (11,049 APIs, 1,570 MCP servers, 3,994 skills, 955 agents, 1,509 services).
- Facilitator: Base mainnet routes to PayAI or CDP when our fee wallet has no gas. 0 merchants yet.
- Payout wallet: 0.307 USDC. Reconciliation: 8 payments confirmed on-chain, 0 problems.
- D1 writes hit 90% of the daily cap this morning; new catalog items are capped at 1,000/day.

## Next, in order

| # | What | Owner | Why |
|---|---|---|---|
| 1 | Apply migration 0014 (drop 2 unused indexes) after 00:00 UTC | A | Saves 2 rows written per catalog write |
| 2 | Dedupe v1 kinds in `/facilitator/supported` | A | Cosmetic, but facilitator directories read it |
| 3 | Real $1 top-up, then a $5 top-up on a referred key | B, **You** approve the spend ($1 approved) | Proves credits and the referral reward end to end. Blocked: this Mac's IP hit the 24 h new-key limit; `scripts/x402-topup-test.mjs` now saves a reusable TEST_API_KEY. The $5 run needs the test wallet funded (1.68 USDC left) |
| 4 | Rescan the CDP Bazaar; list any tool still missing after 48 h | B | Agentic.Market is the biggest discovery channel |
| 5 | Submit the x402 directories in `docs/LISTINGS.md` (x402scan resources and facilitators, x402.eco, x402 Registry, x402.org ecosystem, awesome-agentic-commerce, awesome-x402) | A drafts, **You** approve each | Free reach to x402 buyers and merchants |
| 6 | Republish the MCP Registry entry (66 tools) | A, **You** approve | Registry still shows the earlier description |
| 7 | Own-tool monitor: hourly cron calls a few free tools and alerts on failure | A | We only learn a tool broke when a buyer does |
| 8 | Referral for wallet payers (x402 users have no key): a wallet's first paid call carrying `?ref=CODE` links that wallet to the code's key; the referrer earns **20% of the linked wallet's spend for 90 days**, as credits | B, **You** approve the migration | Most x402 buyers never create a key. A flat $1 per new wallet could be farmed with $0.001 calls from throwaway wallets; a share of real spend can't (it's always less than the spend). Cost: 1 row written per new referred wallet (new `payer_refs` table); earnings are summed from the existing `usage` log, paid out by the daily cron |
| 9 | Facilitator merchant onboarding page: one-line config for x402 sellers, live stats, "gasless, free" | A | 0 merchants today; this is the "Visa" seat |
| 10 | Screenshot tool via Browser Rendering (small free tier) | A, **You** decide | v1 parity |

## Owner actions waiting

- GitHub alert token: give it Issues: Read and write on aipaygen (alerts for payments and the facilitator).
- GitHub repo secrets `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (auto-deploy on master).
- Optional: about $5 of ETH on Base to the facilitator fee wallet, so settlements don't depend on PayAI or CDP.
- Optional: fund the test wallet with $5 USDC for the referral test (item 3).

## Known limits

- D1 free plan: 5M rows read and 100k rows written a day. Measure `rows_read` before shipping any new query.
- Workers free plan: 50 outbound requests per invocation, 10 ms CPU per request.
- Not offered, for terms or cost reasons: YouTube transcripts, Reddit, live stock prices, paid news APIs.
