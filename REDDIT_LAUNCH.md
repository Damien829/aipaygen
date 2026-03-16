# Reddit Launch Post — r/SideProject

## Title
I built an AI API with 250 tools that costs 10x less than calling models directly

## Body

Six months ago I started building an AI tool API on a Raspberry Pi 5 in my apartment. The idea was simple: I kept paying $20/month for OpenAI, $20 for Anthropic, $10 for various scraping tools — and using maybe 2% of what I was paying for. Why isn't there a pay-per-call option that just works?

So I built one. **AiPayGen** is a single API with 250 tools — research, summarize, translate, code generation, web scraping, sentiment analysis, data extraction, and more. 15 AI models from 7 providers (Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama) auto-routed behind the scenes. You pay per call, starting at $0.004.

The whole thing started on a Raspberry Pi 5 and now runs on Oracle Cloud. SQLite for everything, Cloudflare tunnel for TLS, zero external database dependencies. It handles 292 registered agents, 4183 APIs in the catalog, and 2439 skills.

### 3 things you can actually do with it

**1. Research + summarize anything in one API call:**
```bash
curl -X POST "https://api.aipaygen.com/workflow/run" \
  -H "x-api-key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"steps": [
    {"tool": "research", "input": {"topic": "AI agent frameworks 2026"}},
    {"tool": "summarize", "input": {"text": "$prev", "length": "short"}}
  ]}'
```

**2. Scrape + analyze competitor data:**
```bash
curl -X POST "https://api.aipaygen.com/scrape/website" \
  -H "x-api-key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://competitor.com/pricing", "extract": "pricing tiers and features"}'
```

**3. Generate code with the best model for the job (auto-routed):**
```bash
curl -X POST "https://api.aipaygen.com/code" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Python function to parse RSS feeds and extract article summaries", "language": "python"}'
```

### Pricing that doesn't require a spreadsheet

- **Free tier**: 3 calls/day, no API key, no signup — just hit the endpoint
- **Paid**: Load credits from $1. AI calls ~$0.006 each. Utility calls ~$0.002. Scraping ~$0.01.
- **Crypto option**: Pay per call in USDC via x402 protocol (Base, Solana, Stellar) — agents can pay autonomously

For context, calling GPT-4o directly costs ~$0.03 per equivalent request. AiPayGen routes to the best model for the task and charges ~$0.006. Same quality, fraction of the price, because I'm batching calls and optimizing model selection.

### Try it right now (no signup)

The /try page lets you test tools in the browser: https://aipaygen.com/try

Or install the MCP server for Claude/Cursor:
```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

### The stack (for the curious)

Flask + Gunicorn, SQLite in WAL mode, Cloudflare tunnel, Oracle Cloud free tier. 1260 tests passing. 4 cron jobs for auto-maintenance. Started on a Raspberry Pi 5, migrated when I needed more uptime.

Also available on PyPI, MCP Registry, Smithery, and Glama.

---

I'm a solo dev, $0 revenue so far, looking for honest feedback. What would make you actually pay for something like this? What's missing? What feels off?

**Links:**
- Try free: https://aipaygen.com/try
- Pricing: https://aipaygen.com/pricing
- Docs: https://aipaygen.com/docs
- PyPI: https://pypi.org/project/aipaygen-mcp/

---

## Shorter version (r/ClaudeAI)

### Title
I built an MCP server with 250 tools — research, code, scraping, vision, and 43 utility APIs in one install

Just `pip install aipaygen-mcp` and `claude mcp add aipaygen -- aipaygen-mcp`. Or connect to `https://mcp.aipaygen.com/mcp`.

250 tools. 15 AI models auto-routed. Web scraping (Maps, Twitter, YouTube), 43 utility APIs (WHOIS, SSL, geocoding, stocks), vision, RAG, diagrams, workflows.

Free: 3 calls/day. Paid: $0.006/call for AI, $0.002 for utilities. Also supports x402 crypto payments (USDC on Base/Solana/Stellar).

Built by a solo dev. $0 revenue. Looking for feedback.

Try without installing: https://aipaygen.com/try

---

## One-liner (r/selfhosted)

### Title
I run a 250-tool AI API on Oracle Cloud (started on a Raspberry Pi 5) — MCP server, 15 models, SQLite, Cloudflare tunnel

Full write-up in comments. `pip install aipaygen-mcp` to try it. Free tier: 3 calls/day. Serves 292 agents, 4183 APIs, 2439 skills. SQLite WAL mode, Gunicorn with 2 workers, 4 cron jobs for auto-maintenance. 1260 tests passing.

---

## Subreddits to post:
1. **r/SideProject** — primary (full post, feedback angle)
2. **r/MCP** — MCP users (shorter version, install-focused)
3. **r/ClaudeAI** — Claude users (shorter version)
4. **r/artificial** — AI tools audience (full post)
5. **r/selfhosted** — infrastructure angle (one-liner + comments)
6. **r/crypto** — x402/USDC payment angle (marketplace + escrow focus)
