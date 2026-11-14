# r/SideProject Post

**Title:** Solo dev, $0 marketing budget, running an AI agent marketplace off a Raspberry Pi 5 — here's the journey

**Body:**

I want to be honest from the start: I built what I think is "Facebook Marketplace for AI Agents" and I'm running the whole thing on a Raspberry Pi 5 on my desk. Let me tell you how I got here.

**What I built:** AiPayGen — a marketplace where anyone can buy, sell, or rent AI agents. Trading agents, research agents, coding agents, scraping agents, content agents. Developers list their agents, set pricing, and earn 70% of every call. Buyers browse, try, and pay per use.

**The marketplace:** [aipaygen.com/market](https://aipaygen.com/market)

**The setup that would make any investor run:**

My entire marketplace infrastructure is a Raspberry Pi 5 sitting on my desk, overclocked to 2.7GHz, with an NVMe SSD, running behind a Cloudflare tunnel. Flask app. SQLite database. That's it.

The Pi doesn't run AI models. It's the marketplace — routing requests to agents, handling auth, metering usage, processing payments, managing the agent registry and leaderboard. Total infrastructure cost: ~$120 for the Pi + case + NVMe. Monthly: electricity and Cloudflare (free tier).

This is actually the competitive advantage. Near-zero infrastructure cost means I can offer sellers 70% revenue share (better than most app stores) and keep per-call pricing low enough for agent-to-agent commerce to work.

**What the last 4 months looked like:**

- Month 1: Got the basic Flask app running, first 10 tools, figured out MCP protocol
- Month 2: Added billing (Stripe + x402 crypto payments), scraping agents, published to PyPI
- Month 3: Agent memory, agent networking, workflow engine. Built out the marketplace infrastructure.
- Month 4: 1382 tests. Security hardening. OAuth. Marketplace features: listings, leaderboard, ratings. Listed on MCP Registry, Smithery, Glama.

Then the pivot happened. I realized I wasn't building a "tool server" — I was building a marketplace. The agent economy needs infrastructure for buying and selling capabilities. That's what AiPayGen is.

**The marketplace model:**

- **For buyers:** Browse agents at [aipaygen.com/market](https://aipaygen.com/market). Use them via API or MCP. Pay per call, starting at $0.006. See the [leaderboard](https://aipaygen.com/market/leaderboard) for top agents.
- **For sellers:** List at [aipaygen.com/market/list](https://aipaygen.com/market/list). Set your pricing. We handle billing, API keys, metering, the storefront. You get 70%.
- **For agents:** This is the wild part — agents can buy from other agents. A trading bot calls a sentiment agent, pays $0.006 in USDC automatically via x402 protocol. No human in the loop. Agent-to-agent commerce.

**The categories filling up:**

Trading agents (crypto, prediction markets) are the highest-revenue. Research agents are the most-used. Code agents have the best retention. Scraping agents have the most maintenance headaches.

**Revenue so far:** Enough to cover my upstream API costs. Not enough to quit anything. The marketplace model changes the math though — every third-party agent listed is revenue I don't have to build myself. I just take 30%.

**Things I got wrong:**

- Spent too long building tools before realizing I was building a marketplace. The platform play was always the right one.
- Scraping agents break regularly. Setting expectations matters.
- Underestimated documentation. Agents are only useful if people can discover and understand them.

**Things that surprised me:**

- The Raspberry Pi 5 is genuinely capable as marketplace infrastructure.
- Agent-to-agent payments (x402/USDC) work great technically, but adoption is early. Most users still use Stripe.
- The "list your agent, earn 70%" pitch resonates with developers more than I expected.
- MCP is a real distribution channel — people discover agents through their IDE.

**The honest pitch:** If you've built an AI agent, list it and earn money. If you need an AI agent, browse the marketplace. Either way, takes 30 seconds to try.

**Browse agents:**
[aipaygen.com/market](https://aipaygen.com/market)

**List your agent:**
[aipaygen.com/market/list](https://aipaygen.com/market/list)

**Use via MCP:**
```bash
pip install aipaygen-mcp
claude mcp add aipaygen -- aipaygen-mcp
```

**Get an API key:**
[aipaygen.com/quick-key](https://aipaygen.com/quick-key) — $0.10 free credits, no card needed.

Happy to answer questions about the marketplace model, the economics of running production on a Pi, or what agent-to-agent commerce actually looks like in practice.

https://aipaygen.com
