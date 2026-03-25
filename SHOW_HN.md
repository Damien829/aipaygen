# Show HN: AiPayGen — 250 AI tools, one API, pay per call ($0.006/request vs $0.03 direct)

I built a pay-per-call AI API with 250 tools behind a single endpoint. Instead of managing API keys for OpenAI, Google, scraping services, etc., you make one request and the system routes to the best model for the task.

**Why:** Calling AI models directly costs ~$0.03/request. Monthly subscriptions waste money if you only need occasional calls. AiPayGen charges ~$0.006/call by batching and routing across 15 models from 7 providers (Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama).

**What's different from OpenRouter / API aggregators:**
- Not just model proxying — 250 ready-made tools (research, summarize, scrape, code, analyze, extract, translate, classify, etc.)
- x402 protocol support — AI agents pay per call in USDC on Base/Solana/Stellar with no signup or API key. The payment travels with the HTTP request.
- Multi-step workflows — chain tools together (research -> summarize -> translate) in one call with 15% discount
- MCP native — `pip install aipaygen-mcp` adds all 250 tools to Claude Code / Cursor / Cline
- Seller marketplace — register your own APIs, set prices, get paid via escrow (3% fee)

**Architecture:**
- Flask + Gunicorn (gthread, 2 workers x 4 threads)
- SQLite in WAL mode for all persistence — no Postgres, no Redis, no external DB
- Cloudflare tunnel for TLS and DDoS protection
- Oracle Cloud (migrated from Raspberry Pi 5 for uptime)
- 1260 tests, 4 cron jobs (auto-discover, auto-update, auto-sweep, WAL checkpoint)
- x402 V2 micropayments — real USDC settlement (~2s on Base, ~400ms Solana)

**Try it:**

```bash
# Free, no key needed
curl "https://api.aipaygen.com/free/time"
curl "https://api.aipaygen.com/data/weather?city=London"

# AI tool (free tier, 1 call/day)
curl -X POST "https://api.aipaygen.com/summarize" \
  -H "Content-Type: application/json" \
  -d '{"text": "Your long text here", "length": "short"}'
```

Interactive demo (no signup): https://aipaygen.com/try

Free tier: 1 call/day. Paid: from $1 (Stripe or USDC).

- API: https://api.aipaygen.com
- PyPI: https://pypi.org/project/aipaygen-mcp/ (v1.9.0)
- MCP Registry: `io.github.Damien829/aipaygen`
