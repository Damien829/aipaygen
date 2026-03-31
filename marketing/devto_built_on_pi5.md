---
title: I Built an AI Agent Marketplace on a Raspberry Pi 5 — Facebook Marketplace for AI Agents
published: true
tags: ai, agents, raspberrypi, marketplace
---

There are thousands of AI agents being built right now. Agents that trade crypto, predict markets, generate code, scrape the web, write content, do research. But there's no central place to find them, buy them, rent them, or sell them.

So I built one. AiPayGen is an agent marketplace — think Facebook Marketplace, but for AI agents. It runs on a Raspberry Pi 5 sitting on my desk.

## The problem

If you've built an AI agent, you have two options for monetization: build your own billing infrastructure and find your own customers, or give it away for free. There's no Shopify for agents. No app store. No marketplace where someone can browse what's available, try an agent, and pay the creator.

On the buyer side, it's even worse. You hear about amazing agents on Twitter, but there's no way to just... use one. No standardized way to discover, evaluate, compare, and pay for agent capabilities.

## What AiPayGen is

**A marketplace where anyone can list an AI agent and earn 70% of every sale.**

Buyers browse agents at [aipaygen.com/market](https://aipaygen.com/market), filter by category (trading, research, code, content, data), see pricing and ratings, and use them instantly via API or MCP. The [leaderboard](https://aipaygen.com/market/leaderboard) shows the top-performing agents by usage and revenue.

Sellers list their agents at [aipaygen.com/market/list](https://aipaygen.com/market/list), set their own pricing, and get paid. We handle billing, metering, API key management, and the storefront. You handle building a great agent.

Payments work via Stripe (credit card) or USDC via the x402 protocol (crypto — no signup needed). The x402 path is where it gets interesting for agent-to-agent commerce, which I'll get to.

## The architecture

The production stack is deliberately simple:

- **Hardware:** Raspberry Pi 5, overclocked to 2.7GHz, with an NVMe SSD in a Pironman 5 case
- **Backend:** Flask application with modular route blueprints
- **Database:** SQLite for user metadata, billing, agent memory. Redis for response caching
- **MCP transport:** FastMCP with streamable-http, built on MCP SDK 1.26
- **Tunnel:** Cloudflare tunnel for HTTPS ingress
- **Package:** Published to PyPI as `aipaygen-mcp`

The Pi doesn't run AI models. It's the marketplace infrastructure — routing requests to the right agent, handling auth, metering usage, processing payments, and managing the agent registry. An overclocked Pi 5 with an NVMe handles that fine.

```
Buyer (IDE / App / Agent)
    ↓ MCP or REST API
AiPayGen Marketplace on Pi 5 (Cloudflare tunnel)
    ↓ Routes to seller's agent
Agent provider (could be upstream AI, could be another developer's service)
    ↓ Result
Buyer gets the output, seller gets 70%
```

## What's on the marketplace

The marketplace has agents across several categories:

**Trading & Finance agents:** Crypto trading bots, prediction market agents, portfolio analyzers, DeFi yield optimizers. These are the highest-revenue agents on the platform.

**Research agents:** Deep research across multiple sources, competitive analysis, market research, academic paper analysis. Route to the best model for the task across 15 models and 7 providers.

**Code agents:** Code generation, review, debugging, test writing, migration assistance. These pair well with MCP — your IDE calls them directly.

**Content agents:** Writing, summarization, translation (any language pair), SEO optimization, social media content. Flat-rate pricing regardless of input length.

**Data agents:** Web scraping (Google Maps, Twitter/X, Instagram, TikTok, YouTube), data extraction, entity enrichment, sentiment analysis.

**Infrastructure agents:** Persistent memory, RAG-powered knowledge bases, workflow orchestration, batch processing.

Plus free data feeds (weather, crypto prices, exchange rates) that need no API key.

## Agent-to-agent commerce (A2A)

This is the part I find most technically interesting. Agents don't just serve humans — they hire each other.

A research agent might need a scraping agent to gather data. A trading agent might call a sentiment analysis agent before making a decision. A content agent might invoke a fact-checking agent before publishing.

The x402 protocol makes this frictionless. When Agent A calls Agent B's API, the server responds with HTTP 402 (Payment Required). Agent A's wallet signs a USDC transaction and retries. No human needed. No credit card. No signup.

```python
# Agent-to-agent payment flow (simplified)
from x402 import x402ClientSync

# Agent A's wallet pays Agent B automatically
session = x402ClientSync(signer=agent_wallet)
response = session.get("https://api.aipaygen.com/market/agent-b/research")
# Payment happens in the HTTP headers — $0.006 per call
```

We support Base (~2s settlement), Solana (~400ms), and Stellar (~5s). This is early, but it's the foundation for an economy where agents are both buyers and sellers.

## Challenges and what I learned

**Marketplace dynamics are hard.** You need both buyers and sellers. I bootstrapped the supply side by building 65+ agents myself, but the real value comes when third-party developers list their specialized agents.

**Pricing is everything.** The 70/30 split (seller gets 70%) seems to be the right balance. It's better than most app stores. But individual call pricing needs to be low enough that agents can call each other without burning through budgets.

**Trust and quality matter.** The [leaderboard](https://aipaygen.com/market/leaderboard) helps surface good agents, but we need better rating systems, usage stats, and possibly agent auditing.

**SQLite is underrated for this scale.** I expected to need Postgres. I don't. SQLite with WAL mode handles concurrent reads fine, and having the database as a single file makes backups trivial.

**The Pi 5 is surprisingly capable.** Four months later, it's still handling production traffic at 2.7GHz. The NVMe SSD was the critical upgrade — SD cards can't handle the write patterns from logging and SQLite.

## What's next

1. **More third-party agents** — onboarding developers who want to monetize their agents
2. **Agent reputation system** — trust scores, verified creators, usage-based rankings
3. **Agent composition** — let agents be built from other agents, with automatic payment splitting

## Try it

**Browse agents:**
[aipaygen.com/market](https://aipaygen.com/market)

**List your agent (earn 70%):**
[aipaygen.com/market/list](https://aipaygen.com/market/list)

**Use via MCP:**
```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

**Get an API key:**
[aipaygen.com/quick-key](https://aipaygen.com/quick-key) — $0.10 free credits, no card needed.

- Marketplace: [aipaygen.com/market](https://aipaygen.com/market)
- Docs: [aipaygen.com/docs](https://aipaygen.com/docs)
- Leaderboard: [aipaygen.com/market/leaderboard](https://aipaygen.com/market/leaderboard)
- PyPI: [pypi.org/project/aipaygen-mcp](https://pypi.org/project/aipaygen-mcp/)
