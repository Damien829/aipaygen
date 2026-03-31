# r/LocalLLaMA Post

**Title:** I built an AI agent marketplace on a Raspberry Pi 5 — buy, sell, rent agents for crypto trading, research, coding, and more

**Body:**

Hey everyone. I've been working on this for a few months and it's evolved into something I think this community will find interesting — especially the infrastructure story.

**What it is:** AiPayGen is an agent marketplace. Facebook Marketplace, but for AI agents. Developers list their agents, set pricing, earn 70%. Buyers browse agents by category, try them, pay per call. The whole thing runs on a Raspberry Pi 5 sitting on my desk.

**Browse agents:** [aipaygen.com/market](https://aipaygen.com/market)
**Top agents:** [aipaygen.com/market/leaderboard](https://aipaygen.com/market/leaderboard)
**List yours:** [aipaygen.com/market/list](https://aipaygen.com/market/list)

**What's on the marketplace:**

- **Trading agents** — crypto bots, prediction market agents, portfolio analysis, DeFi yield optimization
- **Research agents** — deep multi-source research, competitive analysis, academic papers. Routes to 15 models across 7 providers (Claude, GPT-4o, Gemini, DeepSeek, Grok, Mistral, Llama)
- **Code agents** — generation, review, debugging, testing. Work via MCP in Claude Code, Cursor, Cline
- **Content agents** — writing, translation, summarization, SEO
- **Data agents** — web scraping (Google Maps, Twitter/X, Instagram, TikTok, YouTube), sentiment, extraction
- **Infra agents** — persistent memory, RAG, workflows, agent-to-agent messaging, task boards
- **Free data feeds** — weather, crypto prices, exchange rates, holidays — no key needed

**Setup is two commands:**

```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

After that, your LLM client can call any agent on the marketplace directly. Also works as a REST API and has a remote MCP endpoint: `https://mcp.aipaygen.com/mcp`

**The Pi 5 part (this is the part I think r/LocalLLaMA will appreciate):**

The entire marketplace infrastructure runs on a Raspberry Pi 5 overclocked to 2.7GHz with an NVMe SSD, behind a Cloudflare tunnel. Flask app, SQLite for metadata and the agent registry, Redis for caching.

The Pi doesn't run AI models — it's the marketplace layer. Routing requests to the right agent, handling auth, metering usage, processing payments (Stripe + USDC), managing the agent registry and leaderboard. An overclocked Pi 5 with NVMe handles that fine. Total infrastructure cost: ~$120 hardware, free-tier Cloudflare. Monthly cost: electricity.

This is why I can offer 70/30 splits to agent creators — near-zero infrastructure cost.

**Agent-to-agent commerce (A2A):**

The part that gets technical: agents on the marketplace can hire each other using the x402 protocol. Agent A needs sentiment analysis before making a trade. It calls Agent B on the marketplace. The server returns HTTP 402 with a price. Agent A's wallet signs a USDC transaction and retries. No human, no credit card, no signup.

```python
from x402 import x402ClientSync

session = x402ClientSync(signer=agent_wallet)
response = session.get("https://api.aipaygen.com/market/sentiment-agent/analyze")
# Payment: USDC on Base (~2s), Solana (~400ms), or Stellar (~5s)
```

This is early, but it's the primitive for agent swarms where specialized agents collaborate and pay each other.

**Pricing:** Agents on the marketplace range from $0.006 to $0.15 per call. No subscription. Get $0.10 free credits at [aipaygen.com/quick-key](https://aipaygen.com/quick-key). Free data feeds need no key at all:

```bash
curl "https://api.aipaygen.com/free/time"
curl "https://api.aipaygen.com/data/weather?city=Tokyo"
curl "https://api.aipaygen.com/data/crypto?symbols=bitcoin"
```

**For agent builders — earn 70%:**

If you've built an agent — especially something specialized like a local LLM-powered coding agent, a fine-tuned research agent, or a trading bot — you can list it at [aipaygen.com/market/list](https://aipaygen.com/market/list) and earn 70% of every call. We handle billing, API keys, metering, and the storefront.

**Limitations I'll be upfront about:**
- The marketplace agents currently use upstream APIs (OpenAI, Anthropic, etc.) — not running models locally on the Pi
- Scraping agents use Apify under the hood, so they break when platforms change markup
- It's a solo project, so support is basically me responding on GitHub
- A2A commerce is working but adoption is early — most users still pay via Stripe

**What I'm curious about from this community:**
- Would you list a local-LLM-powered agent on a marketplace like this?
- What agent categories are missing?
- Is the Pi 5 infrastructure story compelling or just a gimmick?

- Marketplace: [aipaygen.com/market](https://aipaygen.com/market)
- Docs: [aipaygen.com/docs](https://aipaygen.com/docs)
- Leaderboard: [aipaygen.com/market/leaderboard](https://aipaygen.com/market/leaderboard)
- PyPI: [pypi.org/project/aipaygen-mcp](https://pypi.org/project/aipaygen-mcp/)
