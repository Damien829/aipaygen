# AiPayGen

<!-- mcp-name: io.github.Damien829/aipaygen -->

**165 AI tools in one MCP server.** Research, write, code, translate, scrape, analyze, vision, RAG, agent memory, workflows, and more. 15 AI models from 7 providers. Pay per call with credit card or USDC.

[![PyPI](https://img.shields.io/pypi/v/aipaygen-mcp)](https://pypi.org/project/aipaygen-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Install (30 seconds)

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

Or connect to the remote server: `https://mcp.aipaygen.com/mcp`

## What's included (165 tools)

**AI tools (40+):** research, write, summarize, translate, code, analyze, sentiment, classify, extract, compare, explain, plan, decide, debate, proofread, rewrite, pitch, headline, keywords, questions, outline, and more

**Advanced AI:** vision (image analysis), RAG (document Q&A), diagram generation, workflow orchestration, pipelines, batch operations, multi-step chains

**Web scraping (6):** Google Maps, Twitter/X, Instagram, TikTok, YouTube, any website

**Data feeds (free):** weather, crypto prices, exchange rates, holidays, time, UUID, jokes, quotes

**Utility APIs (43):** geocoding, WHOIS, SSL certs, security headers, tech stack detection, PDF extraction, stock history, forex, unit conversion, JSON/CSV/XML transforms, ENS resolution, and more

**Agent infrastructure:** persistent memory, agent-to-agent messaging, task boards, knowledge base, 4183 API catalog, 2200+ skills

**Agent builder:** create custom agents from 10 templates. Schedule on loops, cron, or event triggers.

**Seller marketplace:** register your own APIs, set prices, get paid in USDC with escrow.

**Account tools:** `generate_api_key`, `buy_credits`, `check_usage` — manage your account without leaving your IDE.

## Pricing

- **Free tier:** 10 calls/day, no key needed
- **API key:** from $1 via credit card (Stripe). ~166 AI calls per dollar.
- **x402 USDC:** pay per call on Base, Solana, or Stellar — no signup needed
- **Trial credits:** generate a key via the MCP `generate_api_key` tool and get $0.25 free

| Tier | Price | Examples |
|------|-------|---------|
| Free | $0 | weather, crypto, time, jokes, quotes |
| Standard | $0.002/call | memory, geocoding, WHOIS, transforms |
| AI | $0.006/call | summarize, sentiment, classify, translate |
| Scraping | $0.01/call | website, tweets, YouTube |
| Premium | $0.05/call | vision, Google Maps |
| Enterprise | $0.15/call | deep research |

## Try it

```bash
# Free — no key needed
curl "https://api.aipaygen.com/free/time"
curl "https://api.aipaygen.com/data/weather?city=London"
curl "https://api.aipaygen.com/data/crypto?symbols=bitcoin"

# AI (uses free tier, 10/day)
curl -X POST "https://api.aipaygen.com/summarize" \
  -H "Content-Type: application/json" \
  -d '{"text": "Your text here", "length": "short"}'
```

## Configuration

### Claude Code
```bash
claude mcp add aipaygen -- aipaygen-mcp
```

### Claude Desktop / Cursor
```json
{
  "mcpServers": {
    "aipaygen": {
      "command": "aipaygen-mcp"
    }
  }
}
```

### With API key (unlimited)
```bash
AIPAYGEN_API_KEY=apk_xxx aipaygen-mcp
```

### Remote (no install)
```
https://mcp.aipaygen.com/mcp
```

## Technical details

- **15 AI models, 7 providers:** Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama — auto-routed by task
- **x402 V2 micropayments:** Base (~2s), Solana (~400ms), Stellar (~5s) — real USDC settlement
- **MCP SDK 1.26** with streamable-http transport
- **1382 tests passing**
- Published on [MCP Registry](https://registry.modelcontextprotocol.io), [Smithery](https://smithery.ai), and [Glama](https://glama.ai)

## Links

| Resource | URL |
|----------|-----|
| Website | https://aipaygen.com |
| Try free | https://aipaygen.com/try |
| Docs | https://aipaygen.com/docs |
| Pricing | https://aipaygen.com/pricing |
| API | https://api.aipaygen.com |
| MCP remote | https://mcp.aipaygen.com/mcp |
| Service catalog | https://aipaygen.com/discover |
| GitHub | https://github.com/Damien829/aipaygen |

## License

[MIT](LICENSE)
