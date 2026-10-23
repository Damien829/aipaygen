# AIPayGen Site Intel

Pay-per-call website and company intelligence for AI agents, served over
**MCP** and a plain **HTTP API**, paid with **prepaid credits** or **x402 USDC**.
Runs on Cloudflare Workers: no server to keep alive.

| Tool | What it does | Price |
|---|---|---|
| `dns_lookup` | DNS records, DNS host, email provider | $0.001 |
| `security_headers` | HTTP security headers grade A–F | $0.001 |
| `domain_whois` | Registrar, created/expiry dates, age (RDAP) | $0.002 |
| `email_security` | SPF / DMARC / DKIM / MTA-STS grade, spoofability | $0.002 |
| `site_metadata` | Title, socials, contact emails, key pages, schema.org org | $0.002 |
| `page_to_markdown` | Main page content as clean Markdown | $0.002 |
| `ssl_certificates` | Current cert, expiry, every subdomain from CT logs | $0.003 |
| `tech_stack` | 90+ technologies with evidence | $0.003 |
| `company_profile` | One-call company enrichment from a domain | $0.01 |
| `domain_report` | Everything above in one report | $0.02 |

Free: `pricing`, `create_api_key`, `account_balance`. Failed calls are never charged.

## Use it

```bash
# Free key with trial credits
curl -X POST https://aipaygen.com/v1/keys

# HTTP
curl "https://aipaygen.com/v1/company_profile?domain=figma.com" -H "Authorization: Bearer apg_..."

# Claude Code
claude mcp add --transport http aipaygen https://mcp.aipaygen.com/mcp --header "Authorization: Bearer apg_..."
```

Without a key, paid endpoints answer `402 Payment Required` with x402 v2
requirements (`PAYMENT-REQUIRED` header); x402 clients pay and retry with
`PAYMENT-SIGNATURE`. Over MCP the payment goes in `_meta["x402/payment"]`.

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
src/tools/          the Site Intel tools
src/pages.ts        landing, docs, billing, llms.txt, OpenAPI, server card
migrations/         D1 schema
test/               Vitest unit tests
```

The previous Python version (v1) lives on in the git history of the GitHub repo.
