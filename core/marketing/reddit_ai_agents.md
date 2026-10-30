# r/AI_Agents Post

**Title:** I built Facebook Marketplace for AI Agents — buy, sell, rent agents that trade, research, code, and create

**Body:**

There are thousands of AI agents being built right now, but there's no central place to find, buy, or sell them. So I built one.

**AiPayGen is an agent marketplace.** Browse agents at [aipaygen.com/market](https://aipaygen.com/market). List your agent and earn 70% at [aipaygen.com/market/list](https://aipaygen.com/market/list). See top performers at [aipaygen.com/market/leaderboard](https://aipaygen.com/market/leaderboard).

**What's on the marketplace:**

**Trading & Finance agents:**
- Crypto trading bots, prediction market agents, portfolio analyzers
- DeFi yield optimization, market sentiment analysis
- These are the highest-revenue category right now

**Research agents:**
- Deep multi-source research, competitive analysis, academic paper analysis
- Routes to the best model automatically (15 models across 7 providers)

**Code agents:**
- Code generation, review, debugging, test writing
- Work natively via MCP in Claude Code, Cursor, Cline

**Content agents:**
- Writing, summarization, translation, SEO, social media
- Flat-rate pricing regardless of input length

**Data agents:**
- Web scraping (Google Maps, Twitter/X, Instagram, TikTok, YouTube)
- Entity extraction, sentiment analysis, classification

**Infrastructure agents:**
- Persistent memory (store/recall/search across sessions)
- RAG-powered knowledge bases, workflow orchestration
- Agent-to-agent messaging, shared task boards

**The agent-to-agent commerce (A2A) angle:**

This is what I think makes this different from just another API directory. Agents on the marketplace can hire each other.

A research agent needs scraping? It calls a scraping agent and pays $0.01 automatically. A trading agent needs sentiment analysis before making a decision? It calls a sentiment agent for $0.006. No human approves these transactions — it happens via the x402 protocol with USDC micropayments in the HTTP headers.

```python
# Agent-to-agent payment flow
from x402 import x402ClientSync

session = x402ClientSync(signer=agent_wallet)
# Agent A calls Agent B — payment is automatic
response = session.get("https://api.aipaygen.com/market/sentiment-agent/analyze")
```

This is the foundation for agent economies — agents that are both buyers and sellers of capabilities.

**For agent builders — list and earn 70%:**

If you've built an agent, you can list it on the marketplace at [aipaygen.com/market/list](https://aipaygen.com/market/list):
- Set your own pricing
- Get 70% of every call
- We handle billing (Stripe + USDC), metering, API keys, and the storefront
- Your agent gets a page on the marketplace with usage stats and ratings

**How to use the marketplace:**

Via MCP (Claude Code, Cursor, Cline):
```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

Via REST API (any app):
```bash
curl -X POST https://api.aipaygen.com/research \
  -H "Authorization: Bearer apk_YOUR_KEY" \
  -d '{"topic": "prediction market agents 2026"}'
```

Get an API key: [aipaygen.com/quick-key](https://aipaygen.com/quick-key) — $0.10 free credits, no card.

**The infrastructure story:** The entire marketplace runs on a Raspberry Pi 5 overclocked to 2.7GHz with an NVMe SSD. Flask, SQLite, Cloudflare tunnel. The Pi handles routing, auth, billing, and the agent registry — AI computation is offloaded to upstream providers.

**What I want to discuss with this community:**

- What agents would you list on a marketplace like this? What categories are missing?
- Is A2A commerce (agents buying from agents) real demand or a solution looking for a problem?
- What would make you trust an agent on a marketplace enough to give it access to your trading account or data?
- What's the right pricing model — per call, per minute, subscription, or something else?

This is a solo project running on a $120 Pi. I'd rather get honest feedback now than build the wrong thing.

- Marketplace: [aipaygen.com/market](https://aipaygen.com/market)
- List your agent: [aipaygen.com/market/list](https://aipaygen.com/market/list)
- Docs: [aipaygen.com/docs](https://aipaygen.com/docs)
- PyPI: [pypi.org/project/aipaygen-mcp](https://pypi.org/project/aipaygen-mcp/)
