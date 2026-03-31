# HackerNews Show HN — Agent Marketplace

## RECOMMENDED: Version 1 (Technical/Marketplace-focused)

**Title:** Show HN: AiPayGen – An agent marketplace where you buy, sell, and rent AI agents (runs on a Pi 5)

**First comment:**

Hey HN, I built AiPayGen — a marketplace for AI agents. Think Facebook Marketplace, but for AI agents. Developers list their agents, set pricing, and earn 70%. Buyers browse, try, and pay per call. The whole thing runs on a Raspberry Pi 5 on my desk.

Browse agents: https://aipaygen.com/market
List your agent: https://aipaygen.com/market/list
Top agents: https://aipaygen.com/market/leaderboard

The marketplace has agents for trading (crypto, prediction markets), research (multi-source deep dives), code (generation, review, debugging), content (writing, translation, summarization), data (web scraping, sentiment, extraction), and infrastructure (memory, RAG, workflows).

There are two ways to use it:

**MCP** (for Claude Code / Cursor / Cline):
```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

**REST API** (for any app):
```bash
curl -X POST https://api.aipaygen.com/research \
  -H "Authorization: Bearer apk_YOUR_KEY" \
  -d '{"topic": "AI agent marketplace trends"}'
```

The part I think HN will find interesting: **agent-to-agent commerce via x402**. Agents can hire other agents and pay each other in USDC — no human in the loop. A trading agent calls a sentiment agent, pays $0.006 automatically via HTTP 402 headers, gets the result. Base (~2s), Solana (~400ms), or Stellar (~5s) settlement. It's HTTP-native micropayments for machine-to-machine commerce.

Backstory: the entire marketplace infrastructure runs on a Raspberry Pi 5 overclocked to 2.7GHz with an NVMe SSD. The Pi handles routing, auth, billing, and the agent registry. AI computation happens on upstream providers. Total infra cost: ~$120 hardware, free-tier Cloudflare.

Pricing is pay-per-call starting at $0.006. No subscriptions. Sellers get 70%. $0.10 free credits to try it.

Happy to answer questions about the marketplace model, A2A payments, or why I'm running this on an ARM SBC.

Docs: https://aipaygen.com/docs
PyPI: https://pypi.org/project/aipaygen-mcp/

### Follow-up answers:

**Q: "How is this different from OpenRouter or other AI API aggregators?"**
OpenRouter routes LLM inference — you pick a model and send it a prompt. AiPayGen is a marketplace for complete agents — packaged capabilities with specific functions, pricing, and ratings. The difference is "access to GPT-4" vs. "access to a trading agent that uses GPT-4 + scraping + sentiment analysis + portfolio logic." Also, third-party developers can list and monetize their own agents here. It's a two-sided marketplace, not a proxy.

**Q: "Why would I list my agent here instead of selling it myself?"**
Same reason you'd list on Etsy instead of building your own e-commerce site. Distribution, billing, API key management, metering, and a storefront — all handled. You focus on building a good agent. We handle the commerce layer.

**Q: "Agent-to-agent payments — is anyone actually doing this?"**
Honestly, it's early. Most usage is still human-initiated via Stripe. But x402 is the right primitive for A2A commerce — it's HTTP-native, doesn't require accounts, and settles in seconds. When agent swarms become common, the payment layer needs to already exist. We're building it now.

**Q: "Running production on a Pi 5? How does that scale?"**
The Pi handles marketplace infrastructure — routing, auth, billing, registry. AI computation is offloaded. If traffic outgrows it, I'll move to a VPS. But near-zero infra cost means I can offer 70/30 splits to sellers and sustain it solo.

---

**Posting tips:**
- Tuesday-Thursday, 8-10 AM Pacific
- Post first comment within 5 minutes
- Respond to every comment for 2 hours
- Be technical, honest, humble
- Never ask for upvotes
