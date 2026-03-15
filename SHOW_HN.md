# Show HN: AiPayGen — 244 AI tools in one MCP server, pay-per-call in USDC, runs on a Raspberry Pi

I built an MCP server with 244 tools — research, write, code, translate, analyze, scrape, agent memory, workflows, and 43 utility APIs. One install, one API key, 15 AI models from 7 providers behind the scenes. 1382 tests passing (zero failures).

It runs on a Raspberry Pi 5. The entire platform — 287 registered agents, 4183 APIs, 2200 skills — served from an $80 board behind a Cloudflare tunnel.

**Free tier: 10 calls/day, no key needed.** After that, prepaid API keys from $5 (Stripe) or pay-per-call in USDC via x402 V2 (Base, Solana, Stellar). Agents pay autonomously — no signups, no API keys.

---

## Install (30 seconds)

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

Or use the remote server directly: `https://mcp.aipaygen.com/mcp` (streamable-http)

Published on the official MCP Registry (`io.github.Damien829/aipaygen`), Smithery, and Glama.

---

## What's included (244 tools)

**AI tools (40):** research, write, summarize, translate, code, analyze, sentiment, classify, extract, compare, explain, plan, decide, debate, proofread, rewrite, pitch, headline, and more

**Advanced AI (7):** vision (image analysis), RAG (document Q&A), diagram generation, workflow orchestration, pipelines, batch operations, multi-step chains

**Web scraping (6):** Google Maps, Twitter/X, Instagram, TikTok, YouTube, any website — powered by Apify

**Data feeds (free, 8):** weather, crypto prices, exchange rates, holidays, time, UUID, jokes, quotes — no API key needed

**Utility APIs (43):** geocoding, WHOIS, SSL certs, domain enrichment, security headers audit, tech stack detection, PDF extraction, stock history, forex, unit conversion, JSON/CSV/XML/YAML transforms, ENS resolution, and more

**Agent infrastructure:** persistent memory, agent-to-agent messaging, task boards, knowledge base, 4183 API catalog, 2200 skills

**Agent builder:** create custom agents from 10 templates (research, monitor, content, sales, support, data pipeline, security, social, SEO, custom). Schedule on loops, cron, or event triggers.

**Seller marketplace:** register your own APIs, set prices, get paid in USDC with escrow. 3% platform fee.

**Buyer SDK:** auto-402 handling + policy engine — your agent pays for API calls automatically based on rules you set.

---

## Why this exists

Most AI tool services charge monthly subscriptions even if you use them twice a month. x402 V2 flips that: AI agents pay per call in USDC across Base, Solana, or Stellar — no signups, no API keys, just send payment with the request. Backed by the x402 Foundation (Coinbase, Cloudflare, Google, Visa). Google AP2 compatible. This is the only x402 V2-native AI tool marketplace.

One MCP server means any Claude Code / Cursor / Cline user gets 244 tools without managing separate API keys for OpenAI, Google, scraping services, etc. Install once, use everything.

---

## Try it (no install needed)

Interactive demo: https://aipaygen.com/try?ref=hackernews

```bash
# Free endpoints — no key required
curl "https://api.aipaygen.com/free/time"
curl "https://api.aipaygen.com/data/weather?city=London"
curl "https://api.aipaygen.com/data/crypto?symbols=bitcoin"

# AI endpoint (uses free tier, 10/day)
curl -X POST "https://api.aipaygen.com/summarize" \
  -H "Content-Type: application/json" \
  -d '{"text": "Your text here", "length": "short"}'

# See all endpoints
curl "https://api.aipaygen.com/discover"
```

---

## Technical details

- **Raspberry Pi 5** behind Cloudflare tunnel — yes, the whole thing
- **15 AI models, 7 providers**: Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama — auto-routed by task type
- **Full security audit completed**: SQL injection hardened, auth on all routes, JWT verification, input sanitization
- MCP SDK 1.26 with streamable-http transport
- x402 V2 micropayments — Base (~2s), Solana (~400ms), Stellar (~5s) — real USDC settlement
- Stripe for credit card top-ups
- SQLite for all persistence (WAL mode, no external DB dependencies)
- Multi-step workflows with 15% discount
- 1382 tests passing (zero failures), 3 cron jobs (auto-update, auto-discover, auto-sweep)
- Published on PyPI (v1.8.0), MCP Registry, Smithery, and Glama

GitHub: https://github.com/Damien829/aipaygen
PyPI: https://pypi.org/project/aipaygen-mcp/
API: https://api.aipaygen.com
MCP Registry: https://registry.modelcontextprotocol.io (search "aipaygen")
