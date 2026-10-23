# AIPayGen Site Intel — build plan

## What it is
A pay-per-call toolkit that gives AI agents website and company intelligence
from public data: DNS, domain registration, certificates, tech stack, email
security, page content, and a combined company profile.

Agents reach it two ways:
- **MCP** at `https://aipaygen.com/mcp` (Claude, Cursor, any MCP client)
- **HTTP API** at `https://aipaygen.com/v1/<tool>` (any agent or script)

## Why this niche
x402 Bazaar data (30 days to 2026-10-09): company/website enrichment had
~5,700 paying wallets, third behind chain reads and web search, which are
owned by large data providers. Generic LLM tools (most of the old AIPayGen)
had ~530. Site Intel runs on free public data, so revenue is mostly margin.

## Stack (all current as of Oct 2026)
| Piece | Choice |
|---|---|
| Hosting | Cloudflare Workers (no server, global, free tier) |
| MCP | `@modelcontextprotocol/server` 2.3.1 + `agents/mcp/server` `createMcpHandler` (stateless, MCP 2026-07-28, 2025 clients still work) |
| HTTP | Hono 4 |
| Payments | x402 v2 (`@x402/core`, `@x402/evm`) USDC on Base, **and** prepaid API-key credits (Stripe Checkout) |
| Database | Cloudflare D1 (keys, credit ledger, usage) |
| Cache | Workers Cache API, per-tool TTLs |
| Abuse control | Workers Rate Limiting binding + SSRF guard |
| Tests | Vitest |

## Payments
Every paid call accepts either:
1. `Authorization: Bearer apg_...`: deducts from prepaid credits.
   New keys get a small free trial balance.
2. x402: no account; the agent pays USDC per call. Testnet (Base Sepolia,
   x402.org facilitator) by default; mainnet via `X402_NETWORK=eip155:8453`
   plus Coinbase CDP facilitator keys.

A failed tool call is never charged.

## Tools and prices
| Tool | Price |
|---|---|
| `dns_lookup` | $0.001 |
| `security_headers` | $0.001 |
| `domain_whois` (RDAP) | $0.002 |
| `email_security` (SPF/DMARC/DKIM/MX/MTA-STS) | $0.002 |
| `site_metadata` | $0.002 |
| `page_to_markdown` | $0.002 |
| `ssl_certificates` (CT logs, subdomains) | $0.003 |
| `tech_stack` | $0.003 |
| `company_profile` (combined enrichment) | $0.01 |
| `domain_report` (everything) | $0.02 |
| `pricing`, `account_balance`, `create_api_key` | free |

## Discovery
`/llms.txt`, `/openapi.json`, `/.well-known/mcp/server-card.json`,
`server.json` for the MCP Registry, Bazaar metadata on x402 responses,
then re-list on Glama, mcp.so, Smithery, MCP Registry.

## Phases
1. Core Worker, tools, billing, tests: local
2. Deploy to Cloudflare on testnet; point aipaygen.com at it
3. Stripe + x402 mainnet; directory listings and relaunch posts
4. Later: open marketplace for third-party tools (70/30 split)

## Needs from the owner
- Cloudflare account (domain is already on Cloudflare)
- A wallet address to receive USDC
- Later: Stripe account, Coinbase CDP API keys for mainnet
