# AiPayGen Full Improvement Wave — 2026-03-15

## Problem
244 tools, 1260 tests, multi-chain payments — but $0 revenue. 5,783 funnel events show traffic is mostly bots/crawlers. 6 API keys all created in same second (test data). tool_usage.db has 0 rows. No real users converting.

## Wave 1: Fix Tracking & Bot Filtering
**Goal:** Get honest metrics so we know what's real.

1. **Bot filtering middleware** — filter known bots/crawlers from funnel events using User-Agent detection
2. **Fix tool_usage tracking** — verify _log_tool_usage is actually being called (0 rows suggests MCP server hasn't had real traffic, but Flask /try demo calls should be tracked too)
3. **Add real visitor fingerprinting** — distinguish unique humans from repeat bot hits
4. **Add /analytics endpoint** — admin-only dashboard showing real vs bot traffic

## Wave 2: Conversion & Revenue
**Goal:** Make the path from "curious" to "paying" frictionless.

1. **Instant hero demo** — run a real tool (sentiment or summarize) right on the landing page with pre-filled input, no navigation needed
2. **Stripe Payment Links** — embed direct payment link in 402 JSON responses (one-click buy)
3. **Smarter free tier nudges** — show remaining calls count in every MCP response header
4. **Fix upsell in app.py** — the X_FREE_REMAINING environ-based approach needs verification
5. **Add email gate before 10th free call** — capture leads before they exhaust free tier

## Wave 3: Split mcp_server.py
**Goal:** Make the codebase maintainable.

Split 3,267-line mcp_server.py into:
- `mcp_server.py` — core server setup, metering decorator, main()
- `mcp_tools/ai.py` — AI tools (research, write, summarize, etc.)
- `mcp_tools/scraping.py` — 6 scraping tools
- `mcp_tools/data.py` — utility/data tools
- `mcp_tools/agents.py` — agent builder, network, memory tools
- `mcp_tools/marketplace.py` — seller, catalog, skills tools
- `mcp_tools/free.py` — free tier tools (joke, quote, weather, etc.)
- `mcp_tools/wallet.py` — wallet, billing, costs tools

## Wave 4: SEO & Discovery
**Goal:** Get found by real humans and AI tools.

1. **llms-full.txt** — complete tool descriptions with examples for LLM consumption
2. **Per-tool JSON-LD** — structured data on /discover page for each tool
3. **Sitemap expansion** — add individual tool pages
4. **OpenAPI cleanup** — ensure spec is importable by Cursor/Windsurf/etc.

## Wave 5: Developer Experience
**Goal:** Zero friction from install to first successful call.

1. **3-command quickstart** in README and landing page
2. **Example scripts** — Python, curl, Claude Code config
3. **SDK examples directory** with common use cases

## Execution Order
Waves 1-2 first (metrics + revenue), then 3 (maintainability), then 4-5 (growth).
