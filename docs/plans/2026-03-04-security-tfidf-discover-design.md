# Security Hardening + TF-IDF Wave 4 + Discover UX — Design Doc

**Date:** 2026-03-04
**Scope:** Three workstreams executed together

---

## Workstream 1: `/discover` Smart Content Negotiation

### Problem
`/discover` returns a 100+ service raw JSON blob. Browsers see a wall of unformatted JSON with wallet address prominently displayed. Not useful for human visitors or AI agents wanting a quick overview.

### Solution
Check `Accept` header on `/discover`:
- **`text/html` (browser):** Render a clean HTML page with services grouped into categories (AI Processing, Web Intelligence, Data Feeds, Free Tools, Agent Platform, Scraping). Each service shown as a card with endpoint, method, price, and description. Professional styling with inline CSS. "Try Free Preview" CTA.
- **Otherwise (agent/API):** Return JSON reorganized into:
  - `meta`: name, description, total_services, free_count, categories list
  - `payment`: wallet, network, usdc_contract, payment_scheme
  - `services`: grouped by category instead of flat list
  - Links: openapi, llms_txt, preview

### Files Modified
- `app.py`: Replace `/discover` route (line 3887-4006+) with content-negotiated version

---

## Workstream 2: Security Hardening

### Fix 1: Standardize IP Resolution
**Problem:** 8 locations trust `X-Forwarded-For` header directly — spoofable.
**Fix:** Create `_get_client_ip()` helper that checks `CF-Connecting-IP` → `REMOTE_ADDR`. Replace all X-Forwarded-For usages.

**Locations to fix:**
- Line 912 (referral tracking)
- Line 3140 (referral redirect)
- Line 3238 (free tier status)
- Line 3410 (webhook receive)
- Line 6097 (agents/challenge)
- Line 6111 (agents/verify)
- Line 6492 (free/ip)

### Fix 2: Query String Length Limits
**Problem:** No max length on string query params — abuse vector.
**Fix:** Add early check in `add_cors` or a before_request hook to reject requests with any single query param > 10,000 chars.

### No Fix Needed
- `_ALLOWED_ORIGINS`: Already defined correctly (line 927) with 4 domains
- Rate limiter: In-memory is acceptable for Pi. Resets on restart — acceptable tradeoff.

### Files Modified
- `app.py`: Add `_get_client_ip()`, replace X-Forwarded-For usages, add query string length check

---

## Workstream 3: Wave 4 — TF-IDF for ReAct Agent

### Problem
ReAct agent's `search_skills` tool uses naive SQL `LIKE %query%` (10 results, no relevance scoring). The TF-IDF engine already exists in `skills_search.py` and is used by `/skills/search` and `/ask`, but the ReAct agent bypasses it.

### Fix
1. Add `skills_search_engine` param to `make_tool_handler()` in `react_agent.py`
2. Replace SQL LIKE block (lines 346-358) with `skills_search_engine.search(query, top_n=10)`
3. In `app.py` (line 6892), pass `_skills_engine` to `make_tool_handler()`
4. Same for streaming endpoint (line ~6930+)

### Files Modified
- `react_agent.py`: Update `make_tool_handler()` signature and `search_skills` handler
- `app.py`: Pass `_skills_engine` in both `/agent` and `/agent/stream` endpoints
