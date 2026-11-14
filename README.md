# AIPayGen

A marketplace and payment layer for AI agents. Agents search it, run skills from
it, and pay for what they use with **x402** (USDC on Base) or prepaid credits.
Served over **MCP**, **A2A** and a plain **HTTP API**. Runs on Cloudflare
Workers.

- **Marketplace:** 17,000+ resources agents can search for free: 9,700+ APIs
  (many payable with x402), 1,200+ MCP servers, 4,000+ skills, 950+ agents and
  1,500+ services. Listings are health-checked and trust-ranked, and stay fresh
  from the MCP Registry and the x402 Bazaar.
- **Runnable skills:** `run_skill` runs any marketplace skill on your input.
- **x402 facilitator:** non-custodial `/verify` and `/settle` on Base, for any
  x402 server. See [docs/FACILITATOR.md](docs/FACILITATOR.md).
- **Web and company intelligence:** DNS, WHOIS/RDAP, certificates and
  subdomains, tech stack, email security, page-to-markdown, company profiles.

Failed calls are never charged. Prices are quoted in each `402 Payment Required`
response and by the free `pricing` tool.

## Tools

| Tool | What it does |
|---|---|
| `search_marketplace` | Search APIs, MCP servers, skills, agents and services (free) |
| `find_tool` | Describe a need, get the best working, cheapest API or MCP server and how to call it (free) |
| `run_skill` | Run a marketplace skill on your input |
| `register_agent` | List your agent from its A2A card (free) |
| `dns_lookup` | DNS records, DNS host, email provider |
| `security_headers` | HTTP security headers grade A–F |
| `domain_whois` | Registrar, created/expiry dates, age (RDAP) |
| `email_security` | SPF / DMARC / DKIM / MTA-STS grade, spoofability |
| `site_metadata` | Title, socials, contact emails, key pages, schema.org org |
| `page_to_markdown` | Main page content as clean Markdown |
| `ssl_certificates` | Current cert, expiry, every subdomain from CT logs |
| `tech_stack` | 90+ technologies with evidence |
| `company_profile` | One-call company enrichment from a domain |
| `domain_report` | Everything above in one report |

Also free: `pricing`, `create_api_key`, `account_balance`.

## Use it

```bash
# Claude Code
claude mcp add --transport http aipaygen https://mcp.aipaygen.com/mcp

# Search the marketplace (free, no key)
curl "https://aipaygen.com/v1/catalog/search?q=weather"

# Free key with trial credits, then call a tool
curl -X POST https://aipaygen.com/v1/keys
curl "https://aipaygen.com/v1/company_profile?domain=figma.com" -H "Authorization: Bearer apg_..."
```

Without a key, paid endpoints answer `402 Payment Required` with x402 v2
requirements (`PAYMENT-REQUIRED` header); x402 clients pay and retry with
`PAYMENT-SIGNATURE`. Over MCP the payment goes in `_meta["x402/payment"]`.

**For agents:** [llms.txt](https://aipaygen.com/llms.txt) ·
[A2A agent card](https://aipaygen.com/.well-known/agent-card.json) ·
[x402 resources](https://aipaygen.com/.well-known/x402) ·
[OpenAPI](https://aipaygen.com/openapi.json) ·
[Marketplace](https://aipaygen.com/market)

## Develop

Requires Node.js 22+.

```bash
npm install
npm run db:migrate:local
npm run dev          # http://127.0.0.1:8787
npm test             # unit tests
npm run typecheck
```

## Deploy

```bash
npx wrangler login
npx wrangler d1 create aipaygen          # paste the database_id into wrangler.jsonc
npm run db:migrate:remote
npx wrangler secret put ADMIN_TOKEN
npm run deploy
```

Then set in `wrangler.jsonc` → `vars`:

- `PUBLIC_URL`: `https://aipaygen.com`
- `PAY_TO`: your wallet address (enables x402)
- `X402_NETWORK`: `eip155:84532` (Base Sepolia testnet) or `eip155:8453` (Base mainnet; needs a mainnet facilitator)

Uncomment the `routes` block to serve `aipaygen.com`, and add
`mcp.aipaygen.com` / `api.aipaygen.com` custom domains so existing directory
listings keep working.

Card top-ups: set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` secrets and
point a Stripe webhook (`checkout.session.completed`) at `/billing/webhook`.

## Layout

```
src/index.ts        routes + MCP handler
src/mcp.ts          MCP server (stateless, MCP 2026-07-28 + 2025 clients)
src/http.ts         /v1 HTTP API with x402 headers
src/billing/        API keys + credits (D1), x402, Stripe
src/tools/          the web and company intelligence tools
src/catalog.ts      marketplace search, counts, trust ranking
src/refresh.ts      10-minute cron: health checks, MCP Registry + x402 Bazaar ingest
src/skills.ts       run_skill and new skills from unmet demand
src/facilitator.ts  x402 facilitator (verify, settle, mainnet fee wallet)
src/a2a.ts          A2A message/send
src/admin.ts        owner controls (used by the Mac app)
src/edgecache.ts    edge cache that protects D1's daily read quota
apps/mac/           AIPayGen Control, a native macOS dashboard
core/               the v1 Python marketplace (optional, behind the Worker)
src/pages.ts        landing, docs, billing, llms.txt, OpenAPI, server card
migrations/         D1 schema
test/               Vitest unit tests
```

