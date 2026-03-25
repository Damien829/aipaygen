# r/microsaas Launch Post

## Title
I built a pay-per-call AI API with 250 tools as a solo dev — $0 MRR, here's what I learned

## Body

Hey r/microsaas — sharing my journey building AiPayGen, a pay-per-call AI API.

**The problem I'm solving:**
Developers pay $20/mo for OpenAI, $20/mo for Anthropic, $10/mo for scraping tools — and use maybe 2% of what they pay for. There's no simple pay-per-call option that bundles everything.

**What I built:**
AiPayGen — one API with 250 AI tools. Research, summarize, translate, code gen, web scraping, sentiment analysis, and more. 15 models from 7 providers auto-routed. You pay per call starting at $0.004.

**The stack:**
- Flask + Gunicorn on Oracle Cloud (free tier)
- SQLite in WAL mode (no Postgres, no Redis)
- Cloudflare tunnel for TLS
- Self-hosted Llama 3.2 via Ollama for free tier calls ($0 cost)
- MCP native (works with Claude Code, Cursor)
- x402 crypto payments (USDC on Base/Solana)
- 1432 tests, automated deploys with smoke tests
- Started on a Raspberry Pi 5, migrated for uptime

**Pricing model:**
- Free: 1 call/day (runs on self-hosted Llama, costs me $0)
- Paid: from $0.50. AI calls ~$0.006 each
- No subscriptions. Credits never expire.
- Crypto option for autonomous AI agents

**Current metrics (being honest):**
- 250 MCP tools, 2400+ skills
- 450+ discover page hits/day
- 192 MCP connections/day
- 358 API keys generated
- **$0 MRR** — haven't converted to paid yet
- Cost to run: ~$0/mo (Oracle free tier + self-hosted AI)

**What's working:**
- MCP distribution (Smithery, Glama, MCP Registry) drives discovery
- The /try page converts browsers to tool testers
- PyPI package gets installs
- Near-zero hosting cost means I can run indefinitely

**What's NOT working:**
- 0 paying customers despite 450 daily visitors
- Free tier lowered from 10 to 3 to 1 call/day
- Reddit posts got removed from 3/4 subreddits (spam filters)
- No social proof yet

**Lessons learned:**
1. Build for $0 hosting — Oracle free tier + SQLite + Ollama means I never need to shut down
2. MCP is the distribution channel for AI tools right now
3. Pay-per-call pricing is hard to sell — people are used to subscriptions
4. 250 tools sounds impressive but most users only need 3-4

**What would you do differently?** Should I pivot to a subscription model? Add a "Pro plan" at $9/mo? Or keep iterating on pay-per-call?

**Links:**
- Try it: https://aipaygen.com/try
- Pricing: https://aipaygen.com/pricing
- Docs: https://aipaygen.com/docs

---

## Flair
Use: "Share your MicroSaaS" or "Idea Validation" or whatever fits
