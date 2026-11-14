# AiPayGen Development Knowledge Base

Archive of past design decisions, iterations, and session history. Reference this when reviewing what was tried, what worked, and what was changed.

---

## Project Timeline

### Feb 28, 2026 — Project Start
- First Claude Code session
- Initial AiPayGen API server on Raspberry Pi 5 (2700MHz OC)
- Stack: Python/Flask, SQLite, Cloudflare Tunnel

### March 1-15 — Core API Build
- 65+ AI tool endpoints built
- MCP server published to PyPI (aipaygen-mcp)
- x402 crypto payments integrated (USDC on Base)
- Stripe payments integrated
- Agent builder, memory, messaging, task board systems

### March 20-22 — Revenue Sprint
- Payment enforcement hardened (81+ POST routes in x402)
- Free tier set to 0 calls (must pay or watch ad)
- Expo mobile app built and deployed (app.aipaygen.com)
- CLI routing: Anthropic calls through `claude -p` (Max subscription, $0 cost)

### March 22-23 — OAuth & Security
- Google + GitHub OAuth deployed
- 31-bug audit, datetime fix across 33 files
- Cost optimization, security hardening

### March 24-26 — Polish & Monitoring
- Reddit/Dev.to marketing posts
- PWA mobile fix, DB optimization
- Full audit, iPhone Safari fix, fraud protection

### March 27-28 — Agent Marketplace Launch
- **Phase 1: Agent Marketplace** — browse, search, list, checkout
- **Phase 2: Trading Agents** — strategy engine, exchange connectors, paper trading
- **Phase 3: A2A Commerce** — RFQ system, negotiation, contracts, settlement
- Telegram bot (@Aipaygenbot) for phone management
- Unified Apple-inspired design (moved from hybrid to base.html)
- All marketing posts rewritten for marketplace positioning
- Docs updated with marketplace/trading/A2A endpoints

---

## Design Decisions

### Why Marketplace-First (not Trading-First)
- Trading requires regulatory consideration, exchange integrations
- Marketplace generates revenue immediately (30% cut)
- Existing infrastructure (agent registry, payments, escrow) was 80% there
- Trading agents become a *category* within the marketplace

### Why Apple-Inspired Design (not Hybrid)
- Started with a "hybrid" design: Space Grotesk + Space Mono + Instrument Serif, cosmic dark bg, gold accents
- User found it "too AI-looking" and inconsistent with the main site
- Switched to base.html templates with main.css (Inter font, blue accents, clean minimal)
- Mockups archived in archive/brainstorm-20260328/

### Why CLI Routing for Anthropic
- API key (sk-ant-api03-*) was being charged per-token ($3-6/day)
- User has Claude Max 5x subscription ($200/mo) which includes API usage
- Routed `_call_anthropic()` through `claude -p` subprocess
- auto-update.sh was reverting this every 15 min (changed to every 6h)
- Fix committed to git to survive pulls

### Revenue Model
- Marketplace sales: 70% seller / 30% platform
- A2A transactions: 97% seller / 3% platform
- Trading fees: platform proxies calls, charges per-call
- Free to list agents

---

## Archived Files Index

### Screenshots (archive/screenshots-20260328/)
31 PNG files from design audits, app iterations, and UI reviews.
- audit-1 through audit-10: March 26 site audit
- admin-hq-*: Admin dashboard screenshots
- app-*: Mobile app iterations
- desktop-*, explore-*, final-*: Desktop UI variants
- landing-page-*: Landing page versions

### Brainstorm Mockups (archive/brainstorm-20260328/)
10 HTML mockups from the visual brainstorming session:
- 01-platform-vision.html: Three-layer architecture diagram
- 02-approaches.html: Build approach comparison
- 03-marketplace-home.html: First marketplace home design
- 04-trading-agent-detail.html: Trading agent page
- 05-a2a-network.html: A2A commerce network
- 06-list-agent.html: Creator listing flow
- 07-creative-directions.html: Four design direction options (Terminal, Cosmic Glass, Brutalist, Bento Editorial)
- 08-hybrid-marketplace.html: Chosen hybrid design
- 09-hybrid-agent-detail.html: Hybrid agent detail
- 10-hybrid-a2a-network.html: Hybrid A2A network

### Logs (archive/logs-20260328/)
Server logs from the build period — access, discovery, sweep, health, cloudflared, MCP, updates.

---

## Key Mistakes & Lessons

1. **auto-update.sh running every 15 min** — ran pytest constantly, polluted billing_audit.db with fake data, reverted CLI routing fix. Changed to every 6 hours.

2. **Two design systems fighting** — marketplace had its own CSS (market.css) while the rest of the site used base.html + main.css. Caused "website looks all over the place." Fix: all pages extend base.html.

3. **Listing form requiring JWT** — the POST /marketplace/list endpoint required JWT auth which an HTML form can't provide. Fixed by creating /market/list POST handler that validates API key from form field instead.

4. **app.aipaygen.com serving dead Expo SPA** — old chat app that looked disconnected. Fixed by redirecting to main site.

5. **ANTHROPIC_API_KEY in .env** — caused Claude Code to charge API rates instead of using Max subscription. Not actually the case (Claude Code uses OAuth), but the key was still being used by the Flask server for LLM calls, costing $40 total.

---

## Current Architecture

### Files Structure
```
agent-service/
  app.py              — Flask app, x402 middleware, blueprint registration
  model_router.py     — LLM routing (claude -p for Anthropic, API for others)
  agent_memory.py     — Agent registry, marketplace, reviews, performance
  agent_network.py    — Messaging, tasks, reputation, free tier
  trading_engine.py   — Strategies, trades, portfolios, copy trading
  exchange_connectors.py — Live prices (CoinGecko/Binance/Coinbase), paper executor
  a2a_engine.py       — RFQ, negotiation, contracts, transactions
  seller_marketplace.py — Seller APIs, wallets, escrow, payouts
  agent_identity.py   — JWT + wallet verification
  telegram_bot.py     — @Aipaygenbot management bot
  routes/
    meta.py           — All HTML pages (landing, market, trading, a2a, docs, etc.)
    marketplace.py    — Marketplace API endpoints
    trading.py        — Trading API endpoints
    a2a.py            — A2A commerce API endpoints
    auth.py           — Stripe, API keys, subscriptions
    seller.py         — Seller management
    builder.py        — Agent builder
    network.py        — Agent messaging/tasks
    admin.py          — Admin dashboard
  templates/
    base.html         — Shared template (nav, footer, main.css)
    index.html        — Landing page
    market.html       — Marketplace home
    market_agent.html — Agent detail + "Try This Agent"
    market_list.html  — List your agent form
    market_leaderboard.html
    market_checkout.html
    market_error.html
    trading.html      — Trading dashboard
    trading_detail.html — Strategy detail
    trading_deploy.html — Deploy strategy form
    a2a.html          — A2A network dashboard
    a2a_post_rfq.html — Post RFQ form
    docs.html, pricing.html, etc.
  static/
    css/main.css      — Apple-inspired design system
    market.css        — Old hybrid design (kept but unused)
```

### Databases (43 SQLite files)
- api_keys.db, billing_audit.db — Payment/billing (CRITICAL)
- agent_memory.db — Registry, marketplace, reviews
- agent_network.db — Messaging, tasks, reputation
- trading.db — Strategies, trades, portfolios
- a2a.db — RFQ, contracts, transactions
- seller_marketplace.db — Seller wallets, escrow
- + 36 others (skills, workflows, analytics, etc.)

### External Services
- Stripe (payments) — sk_live_* key
- Anthropic (LLM) — routed through CLI subscription
- Cloudflare Tunnel — free tier
- Resend (email) — free tier
- CoinGecko/Binance/Coinbase — free price APIs
- Telegram Bot API — free

### Cron Jobs
- auto-update.sh — every 6 hours (was 15 min)
- auto-sweep.sh — every 10 min (health checks)
- auto-discover-tools.sh — hourly
- tunnel-watchdog.sh — every minute
- health_monitor.py — every 5 min
- check_payments.py — hourly
- backup_dbs.sh — daily at 3am
- wal-checkpoint.sh — every 6 hours
