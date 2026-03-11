# Reddit Launch Post — r/MCP, r/ClaudeAI, r/artificial

## Title
AiPayGen: 155+ AI tools as one MCP server — pay-per-call in USDC, runs on a Raspberry Pi 5

## Body (r/MCP)

I built **AiPayGen** — an MCP server with 155+ tools you can add to Claude, Cursor, or any MCP client in 30 seconds. 15 AI models from 7 providers, 450/450 tests passing, runs entirely on a Raspberry Pi 5.

### Install:
```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

Or connect to the remote server: `https://mcp.aipaygen.com/mcp`

### What's inside (155+ tools):
- **AI tools (40+)**: research, write, summarize, translate, code, analyze, sentiment, classify, compare, debate, proofread, rewrite, vision, RAG, diagrams, workflows
- **Web scraping (6)**: Google Maps, Twitter/X, Instagram, TikTok, YouTube, any website
- **Utility APIs (43)**: geocoding, WHOIS, SSL certs, security audits, stock history, forex, PDF extraction, JSON/CSV/XML transforms, ENS resolution, tech stack detection
- **Agent infra**: persistent memory, agent messaging, knowledge base, 4155 API catalog, 1968 skills
- **Agent builder**: create custom agents from 10 templates, schedule on cron/loops/events
- **Data feeds** (free): weather, crypto, exchange rates, time, jokes, quotes
- **Seller marketplace**: register your own APIs, set prices, get paid via escrow. 3% fee.
- **Buyer SDK**: auto-402 handling + policy engine — your agent pays for calls automatically

### What makes this different:
1. **155+ tools, one install** — stop juggling API keys for 12 different services
2. **Only x402-native AI marketplace** — AI agents can discover and pay for API calls with USDC autonomously, no signup
3. **Seller marketplace with escrow** — register your own APIs, set prices, get paid
4. **Agent-to-agent network** — 146 registered agents, shared task boards, messaging
5. **15 AI models auto-routed** from 7 providers — Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama
6. **Runs on a Raspberry Pi 5** — the entire platform (4155 APIs, 1968 skills, 136 API keys) served from an $80 board
7. **Security audited** — SQL injection hardened, auth on all routes, full test coverage

### Pricing:
- **Free tier**: 10 calls/day, no API key needed
- **Paid**: Prepaid keys from $5 (Stripe) or pay-per-call in USDC via x402 on Base
- **AI tools**: ~$0.006/call | **Utility tools**: $0.002/call | **Scraping**: $0.01/call

### Example: research + summarize in one workflow
```bash
curl -X POST "https://api.aipaygen.com/workflow/run" \
  -H "x-api-key: apk_your_key" \
  -H "Content-Type: application/json" \
  -d '{"steps": [
    {"tool": "research", "input": {"topic": "quantum computing 2026"}},
    {"tool": "summarize", "input": {"text": "$prev", "length": "short"}}
  ]}'
```

### Links:
- Try it (no install): https://aipaygen.com/try
- Docs: https://aipaygen.com/docs
- PyPI: https://pypi.org/project/aipaygen-mcp/ (v1.7.1)
- MCP Registry: `io.github.Damien829/aipaygen`
- Smithery & Glama: LIVE
- GitHub: https://github.com/Damien829/aipaygen

Happy to answer questions!

---

## Shorter version (r/ClaudeAI)

### Title
I built an MCP server with 155+ tools — one install gives you research, code, scraping, vision, RAG, agent memory, and 43 utility APIs

Just `pip install aipaygen-mcp` and `claude mcp add aipaygen -- aipaygen-mcp`.

155+ tools including web scraping (Google Maps, Twitter, YouTube), 43 utility APIs (WHOIS, SSL, geocoding, stock data), vision, RAG, diagram generation, a seller marketplace with escrow, and a full agent builder with scheduling.

Free tier: 10 calls/day. Paid: $0.006/call for AI tools, $0.002 for utilities. Also supports x402 crypto payments (USDC on Base).

15 AI models from 7 providers auto-routed — Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama.

Runs on a Raspberry Pi 5. 450/450 tests. Security audited.

Try without installing: https://aipaygen.com/try
Remote MCP: `https://mcp.aipaygen.com/mcp`

---

## One-liner (r/selfhosted)

### Title
I run a 155-tool AI API marketplace on a Raspberry Pi 5 — MCP server, 15 AI models, x402 crypto payments, SQLite, Cloudflare tunnel

Full write-up in comments. `pip install aipaygen-mcp` to try it. Free tier: 10 calls/day. Serves 146 agents, 4155 APIs, 1968 skills from a Pi behind a Cloudflare tunnel. SQLite WAL mode, Gunicorn with 2 workers, 3 cron jobs for auto-maintenance.

---

## Subreddits to post:
1. **r/MCP** — primary audience (full post)
2. **r/ClaudeAI** — Claude users (shorter version)
3. **r/artificial** — AI tools audience (full post)
4. **r/SideProject** — indie maker audience (full post, emphasize Pi angle)
5. **r/selfhosted** — Raspberry Pi angle (one-liner + comments)
6. **r/crypto** — x402/USDC payment angle (focus on marketplace + escrow)
