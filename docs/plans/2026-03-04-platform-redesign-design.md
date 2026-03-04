# AiPayGent Platform Redesign — Design Doc

**Date:** 2026-03-04
**Status:** Approved, pending implementation plan

---

## Vision
Transform AiPayGent from a raw API into a **commercial AI agent platform** — marketed like a SaaS product. Agents discover it naturally, humans see a polished brand. Competitive intelligence is protected.

## Architecture — 5 Workstreams

### 1. Website Overhaul (multi-page, eye-catching)
- **`/` (homepage)** — Keep existing dark theme but refine: hero section with animated tagline, 3 value props (138+ tools, x402 native, agent memory), social proof section, CTA → /discover
- **`/discover` (interactive catalog)** — Searchable/filterable service browser. Category tabs, live "try it" buttons for free endpoints. No raw JSON. Links to each service detail. Clicking a service should NOT show raw code — should show a formatted detail page.
- **`/docs`** — Integration guide for agents (x402 flow, SDK examples, MCP setup)
- All pages share consistent nav + footer
- Match existing homepage dark theme (--bg: #020408, --green: #00ff9d, IBM Plex fonts)

### 2. Pricing Restructure — Minimize Freebies
- **Free tier (honeypots only):** `/preview`, `/free/time`, `/free/uuid`, `/free/ip`, `/health`, `/discover`, `/.well-known/agent.json`, `/llms.txt`
- **Everything else is paid** — data endpoints (weather, crypto, stocks, jokes, quotes) move to paid ($0.01 each)
- Remove explicit pricing from public pages — just say "Pay-per-use via x402" without exact per-endpoint prices
- Prices still in x402 402-response headers (required by protocol) but not advertised publicly

### 3. Agent Discovery Layer (SEO for AI)
- **`/.well-known/agent.json`** — Keep but remove detailed pricing breakdown. Just list capabilities + payment method
- **`/llms.txt`** — Slim down to capabilities overview, remove implementation details competitors could copy
- **`/robots.txt`** — Allow crawling of discovery pages, block internal routes
- **`/sitemap.xml`** — Already exists, keep for crawlers

### 4. Service Encryption / Access Control
- **Encrypt service responses** — All paid endpoint responses wrapped: response body encrypted with a session key derived from x402 payment proof. Only the paying agent can decrypt.
- **Rate limit unauthenticated discovery** — `/discover` JSON limited to service names + descriptions only (no input schemas, no implementation hints)
- **Skills DB protection** — `/skills/search` requires auth. No public skill browsing.

### 5. Competitive Protection
- Remove service count ("138+ endpoints") from public pages — replace with category descriptions
- No input/output schemas in public discovery — agents get schemas only after first paid call
- Strip source attribution from skills (don't reveal where skills were harvested from)

## What NOT to do (YAGNI)
- No user accounts/login system
- No dashboard
- No analytics page
- No blog

## Prior Completed Work (same session)
- Security hardening: _get_client_ip(), X-Forwarded-For replaced, query param limits
- ReAct agent upgraded to TF-IDF search
- /discover content negotiation (HTML + JSON) — needs redesign per this doc

## Next Step
Run `/clear` then invoke `superpowers:writing-plans` to create detailed implementation plan from this design.
