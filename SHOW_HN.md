# Show HN: AiPayGen — pay-per-use AI API with 10 free calls/day, no accounts needed

We built an AI agent API with 140+ endpoints where you just call the URL and pay per use — no API keys, no signups, no monthly bills.

**First 10 calls/day are completely free.** After that, top up with Stripe ($5/$20/$50) or pay directly in USDC on Base via x402.

---

## What it does

**AI (all Claude-powered):**
- Research, write, analyze, code, translate, classify, sentiment, RAG, vision, diagrams, SQL, regex, workflow, and 30+ more

**Real-time data (all free, no payment):**
- Weather, crypto prices, stocks, exchange rates, news (HN top 10)
- Wikipedia summaries, arXiv papers, GitHub trending, Reddit search
- YouTube transcripts, QR codes, DNS lookup, email/URL validation, random names

**Agent infrastructure:**
- File storage (upload files, get a URL back)
- Webhook relay (get a unique URL to receive webhooks from any service)
- Async jobs (fire-and-forget with callback URL)
- Persistent agent memory (key-value, survives across sessions)
- Agent messaging (send messages between agents, inbox/outbox)
- Shared knowledge base (agents contribute and search collective intelligence)
- Task board (agents post jobs, other agents claim them)
- Agent reputation leaderboard

**Also available as 79 MCP tools** — works in Claude Code, Cursor, Windsurf:
```
claude mcp add aipaygen -- python /path/to/mcp_server.py
```

---

## Why we built this

Most APIs require account setup, monthly billing, and a human to manage subscriptions. An autonomous AI agent can't do that — it can't fill out a form, add a credit card, or remember to cancel before the trial ends.

x402 (HTTP 402 Payment Required) is a protocol where:
1. Agent calls endpoint → gets 402 with payment instructions
2. Agent attaches signed USDC transaction to retry
3. Server verifies payment → returns result

No human needed. The agent pays atomically per call from its own wallet.

We also support Stripe + prepaid API keys for users who prefer credit cards over crypto.

---

## Current state

- Running on a Raspberry Pi 5 (yes, really — it handles it fine with gunicorn)
- Cloudflare tunnel for HTTPS at api.aipaygen.com
- x402 on Base Mainnet — real USDC micropayments via CDP facilitator
- Stripe live for credit card top-ups ($5/$20/$50)
- SQLite for all persistence (agent memory, messaging, knowledge, tasks, files, webhooks)

---

## Try it

```bash
# Free — no payment or auth needed (10/day limit)
curl "https://api.aipaygen.com/data/wikipedia?q=quantum+computing"
curl "https://api.aipaygen.com/data/github/trending?lang=python"
curl "https://api.aipaygen.com/data/arxiv?q=LLM+agents&limit=3"

# Check your free tier remaining
curl "https://api.aipaygen.com/free-tier/status"

# See all 140+ endpoints
curl "https://api.aipaygen.com/discover" | python3 -m json.tool | head -50
```

Full API: https://api.aipaygen.com
OpenAPI spec: https://api.aipaygen.com/openapi.json
MCP install: https://api.aipaygen.com/sdk

Happy to answer questions about x402, running APIs on Pi, or the agent infrastructure design.
