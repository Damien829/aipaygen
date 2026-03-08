# Show HN: AiPayGen — 106 AI tools as one MCP server, published on the official MCP Registry

I built an MCP server with 106 AI tools — research, write, code, translate, analyze, scrape, agent memory, and more. One install, one API key, 15 AI models behind the scenes.

**Free tier: 10 calls/day, no key needed.** After that, prepaid API keys from $5 (Stripe) or pay-per-call in USDC on Base via x402.

---

## Install

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

Or use the remote server directly: `https://mcp.aipaygen.com/mcp` (streamable-http)

Published on the official MCP Registry: `io.github.Damien829/aipaygen`

---

## What's included (106 tools)

**AI tools:** research, write, summarize, translate, code, analyze, sentiment, classify, extract, compare, explain, plan, decide, debate, proofread, rewrite, pitch, headline, and more

**Advanced AI:** vision (image analysis), RAG, diagrams, workflows, pipelines, batch operations

**Web scraping:** Google Maps, Twitter/X, Instagram, TikTok, YouTube, any website

**Data feeds (free):** weather, crypto, exchange rates, holidays, time, UUID, web search

**Agent infrastructure:** persistent memory, agent-to-agent messaging, task boards, knowledge base, 500+ API catalog

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
- x402 micropayments on Base Mainnet (real USDC)
- Stripe for credit card top-ups
- SQLite for all persistence

GitHub: https://github.com/Damien829/aipaygen
PyPI: https://pypi.org/project/aipaygen-mcp/
API: https://api.aipaygen.com
MCP Registry: https://registry.modelcontextprotocol.io (search "aipaygen")
