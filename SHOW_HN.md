# Show HN: AiPayGen — 153 AI tools as one MCP server, pay-per-call in USDC

I built an MCP server with 153 AI tools — research, write, code, translate, analyze, scrape, agent memory, workflows, and 43 utility APIs. One install, one API key, 15 AI models behind the scenes.

**Free tier: 3 calls/day, no key needed.** After that, prepaid API keys from $5 (Stripe) or pay-per-call in USDC on Base/Solana via x402.

---

## Install

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

Or use the remote server directly: `https://mcp.aipaygen.com/mcp` (streamable-http)

Published on the official MCP Registry: `io.github.Damien829/aipaygen`

---

## What's included (153 tools)

**AI tools:** research, write, summarize, translate, code, analyze, sentiment, classify, extract, compare, explain, plan, decide, debate, proofread, rewrite, pitch, headline, and more

**Advanced AI:** vision (image analysis), RAG, diagrams, workflows, pipelines, batch operations

**Web scraping:** Google Maps, Twitter/X, Instagram, TikTok, YouTube, any website

**Data feeds (free):** weather, crypto, exchange rates, holidays, time, UUID, web search

**Utility APIs (43):** geocoding, WHOIS, SSL certs, domain enrichment, security headers audit, tech stack detection, PDF extraction, stock history, forex, unit conversion, math, JSON/CSV/XML transforms, and more

**Agent infrastructure:** persistent memory, agent-to-agent messaging, task boards, knowledge base, 4000+ API catalog

**Seller marketplace:** register your own APIs, set prices, get paid in USDC — 3% platform fee

---

## Try it (no install needed)

Interactive demo: https://aipaygen.com/try

```bash
# Free endpoints
curl "https://api.aipaygen.com/free/time"
curl "https://api.aipaygen.com/data/weather?city=London"

# See all endpoints
curl "https://api.aipaygen.com/discover"
```

---

## Technical details

- Runs on a Raspberry Pi 5 behind Cloudflare tunnel
- 15 AI models: Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama — auto-routed
- MCP SDK 1.26 with streamable-http transport
- x402 micropayments on Base + Solana (real USDC, ~400ms settlement on Solana)
- Stripe for credit card top-ups
- SQLite for all persistence
- Agent builder: create scheduled agents from templates
- Multi-step workflows with 15% discount

GitHub: https://github.com/Damien829/aipaygen
PyPI: https://pypi.org/project/aipaygen-mcp/
API: https://api.aipaygen.com
MCP Registry: https://registry.modelcontextprotocol.io (search "aipaygen")
