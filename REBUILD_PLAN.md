# AIPayGen Rebuild Plan: bring back the v1 marketplace, modernize it, lock it down

Status: **plan only. No code has been written.** Every phase ends with a check that has to pass before the next phase starts.

---

## What we're working with (audit of 2026-10-30)

| | v1 (commit `36370d3`) | v2 (current `main`) |
|---|---|---|
| What it is | Full agent marketplace: 142 agents, sellers, A2A commerce, workflows, course, products, trading (paper), 253 MCP tools | Site Intel only: 10 website/domain tools |
| Size | 424 files, 584 routes, 155 x402-paid routes, 59 test files | 43 files |
| Stack | Python Flask + gunicorn on a Raspberry Pi behind a tunnel | TypeScript on Cloudflare Workers, D1 database |
| Payments | x402 Python SDK 2.3.0, Stripe, crypto deposits, settlement (5% marketplace / 3% A2A fee) | x402 v2, **live on Base mainnet** to your wallet, Stripe credits |
| Data | ~30 separate SQLite files on the Pi (never in git) | D1 |
| Agent discovery | llms.txt, openapi, agent.json, ai-plugin, mcp.json, x402.json, pay.json, pricing.json, security.txt | llms.txt, openapi, MCP server card, MCP Registry, Bazaar |

The two versions each have something the other lacks. v1 has the business; v2 has the modern, serverless, mainnet-tested payment layer. **The plan combines them instead of picking one.**

### Security findings in v1 (things to fix)
1. **Logs committed to git:** `requests.jsonl` (290 KB, includes IPs and an `api_key` field) and `update.log.old` (1.2 MB). Remove them and keep them out.
2. **Dynamic SQL column names:** `routes/builder.py:592`, `workflow_db.py:115`, `api_catalog.py:71,107`, `accounts.py:45`. Values are parameterized but column names aren't checked against an allowlist. Add strict allowlists.
3. **One shared admin password:** the admin panel takes a single `ADMIN_SECRET` from a form field or header. Replace it with real admin sign-in (Cloudflare Access or passkeys) and audit logs.
4. **Credential vault:** the key lives in `~/.agent_key` on the Pi, and the vault quietly returns `None` when that key is missing. Move it to managed secrets and fail closed.
5. **`Access-Control-Allow-Origin: *` on every response:** fine for the public API, wrong for admin, account and cookie routes.
6. **Prices hard-coded 155 times in `app.py`:** a single typo undercharges or overcharges. Keep one price table as the single source of truth.
7. **Dependencies frozen in March 2026:** Flask, x402 2.3.0, web3, stripe, anthropic and others are 7 months old. Upgrade and scan them.
8. **Single point of failure:** one Pi, one SD card, ~30 SQLite files and a tunnel watchdog script. If the card fails, the business is gone.
9. **Secrets on the Pi:** `.env` has been on a machine exposed through a tunnel. Treat every key as compromised and rotate it.
10. **Marketplace payouts:** settlement collects buyer money and pays sellers later, so the platform holds other people's funds (custody). That is a legal and regulatory risk (money transmission). The fix is in Phase 4.
11. **Trading:** auto-execution and copy trading exist (paper mode by default). Live trading for other users is regulated. Keep it simulation-only and clearly labeled.

No live private keys, API keys or Stripe secrets were found anywhere in the git history. Only placeholders and the public ERC-20 event signature.

---

## Target architecture

```
                    aipaygen.com (Cloudflare)
                              │
              ┌───────────────┴────────────────┐
              │  Edge Worker (TypeScript, v2)  │  ← agents and people land here
              │  • all discovery files         │
              │  • x402 v2 payment gate        │  ← ONE payment layer for everything
              │  • MCP endpoint (all tools)    │
              │  • rate limits, WAF, SSRF guard│
              │  • Site Intel tools (native)   │
              │  • static site + pages         │
              └───────────────┬────────────────┘
                     signed internal requests only
              ┌───────────────┴────────────────┐
              │  Core API (Python, v1 code)    │  ← marketplace, agents, A2A,
              │  container on managed hosting  │     workflows, AI tools, trading sim
              │  Postgres (managed, backed up) │
              └────────────────────────────────┘
```

Why this shape:
- **Your 3 months of Python logic is reused, not rewritten.** Porting 584 routes to TypeScript would take months and bring new bugs.
- **Payments live in one place.** The v2 x402 code already works on mainnet and every paid call goes through it. v1's 155 hand-written price entries go away.
- **The Pi stops being critical.** It can stay as a dev box.
- The Python origin isn't reachable from the internet directly. Only the Worker can call it, with a signed header.

---

## Phases

### Phase 0: Protect what exists (no code)
1. **Back up the Pi before anything else.** Copy every `*.db`, `*.db-wal` and `*.db-shm` file, plus `.env`, `.env.enc` and `~/.agent_key`, to two places (your Mac and encrypted cloud storage). Write down row counts per table.
2. Create the git tag `v2-sitesintel-final` on the current `main` so v2 is easy to find.
3. Create branch `rebuild` from `main`. All work happens there and `main` stays live until cutover.
4. Commit or discard the modified `scripts/x402-pay-test.mjs`.

**Done when:** backups open on another machine and row counts match.

### Phase 1: Bring v1 back into the repo
5. Put v1 under `core/` (the Python service) next to v2's `src/` (the edge Worker). Keep history with `git checkout 36370d3 -- <paths>` into the new layout.
6. Delete the committed logs (`requests.jsonl`, `update.log.old`, `.restart.lock`) and the Pi-only scripts (`tunnel-watchdog.sh`, `auto-update.sh`, `*.service.new`). Tighten `.gitignore`.
7. Run v1's 59 test files as they are and record the baseline (pass/fail counts) before changing anything.

**Done when:** v1 boots locally from `core/` and the baseline is recorded.

### Phase 2: Security hardening (code)
8. Upgrade every dependency to current versions. Run `pip-audit` and `npm audit` until no high or critical issues remain. Add Dependabot or Renovate.
9. Add strict column allowlists to the 5 dynamic-SQL spots and a lint rule that bans f-strings in `execute()`.
10. Replace `ADMIN_SECRET` with Cloudflare Access in front of `/admin` (SSO plus a second factor) and add an admin action audit log.
11. Move all secrets to managed secrets (Worker secrets and the host's secret store). The vault fails closed. Rotate **every** key: Anthropic, OpenAI, Google, Stripe, Resend, CDP, Telegram, OAuth clients and the admin secret.
12. Split CORS: `*` on the public API only; account, admin and session routes are same-origin with secure, HttpOnly, SameSite cookies and CSRF tokens.
13. Add security headers site-wide: CSP, HSTS preload, `X-Content-Type-Options` and `frame-ancestors`.
14. Validate input on every route (pydantic models) with request size limits. Reuse v2's SSRF guard for anything that fetches a URL (scraping, page-to-markdown, webhooks).
15. Webhooks: HMAC-sign outbound calls, verify inbound Stripe signatures, and add replay protection with timestamp and nonce.
16. Add rate limits per IP, per API key and per wallet at the edge.
17. Logs: no raw API keys, IPs hashed, 30-day retention.
18. Add CI security checks: secret scanning (gitleaks), Bandit for Python, CodeQL and a dependency audit. They must pass to merge.

**Done when:** all scanners are clean, the v1 test baseline holds or improves, and new tests cover each fix above.

### Phase 3: Data layer
19. Move ~30 SQLite files into **one managed Postgres** with migrations (Alembic). Each old file becomes its own schema so the migration stays mechanical.
20. Write a migration script that loads the Phase 0 backups. Run it twice, verify that row counts and money totals match exactly, and keep it repeatable.
21. Turn on daily automated backups with point-in-time recovery and run a **monthly restore test**.

**Done when:** a restore from backup gives the same balances.

### Phase 4: One payment layer, done right
22. **One price table** (`pricing.json`, generated once and read by both the Worker and Python). Each entry has: route, price, description, input schema and example.
23. The Edge Worker handles x402 for **all** paid routes using v2's mainnet-tested code. The Python core trusts only the Worker's signed "paid" header.
24. Charge only on success: verify, then run, then settle; if the tool fails, don't settle. v2 already works this way. Add an idempotency key so a retried payment can't charge twice.
25. Replay protection: store each payment's nonce and payer and reject duplicates.
26. **Marketplace payouts without custody:** for third-party agents, the x402 `payTo` is the **seller's own wallet** and the platform fee goes to your wallet as a separate payment requirement or through a split contract. AIPayGen never holds seller funds. Retire the custodial settlement batches. (Get a quick legal check before launch; see "Needs from you".)
27. Support multiple chains: Base (live) plus Solana USDC via the x402 SVM scheme, so more agent wallets can pay.
28. Keep Stripe prepaid credits for people who don't use crypto, on v2's credit ledger.
29. Reconciliation job: each night, compare on-chain receipts with the ledger and alert on any mismatch.
30. End-to-end payment tests on Base Sepolia for every price tier, then one real $0.001 mainnet call per tool group before launch.

**Done when:** testnet e2e passes for all tiers, mainnet smoke passes, and reconciliation shows zero mismatches over 48 hours.

### Phase 5: Built for agents (the "found naturally" part)
31. **One catalog generates all discovery files**, so they can't drift apart:
    - `/llms.txt` and `/llms-full.txt`
    - `/openapi.json` (OpenAPI 3.1, every route with price and schema)
    - `/.well-known/mcp/server-card.json` and MCP Registry `server.json`
    - `/.well-known/agent-card.json` (the A2A agent card)
    - `/.well-known/x402` plus **Bazaar discovery metadata on every 402**, so facilitators list every tool automatically
    - the legacy files (`ai-plugin.json`, `agents.json`, `pay.json`, `pricing.json`) kept for older crawlers
    - `sitemap.xml` and `robots.txt` that explicitly **allow** AI crawlers
32. **Agent-friendly responses:** clear error codes, consistent JSON shape, `Retry-After` on rate limits, and a 402 that explains exactly how to pay. Any page can be served as Markdown when `Accept: text/markdown` is sent.
33. **Free try-before-pay:** a small free tier per wallet or key, so agents can test without friction. This is the top conversion driver.
34. **One MCP endpoint for the whole marketplace:** Site Intel, AI tools and marketplace agents. It uses search-style tool discovery (`search_tools`, `get_tool`) instead of dumping 250+ tools, which overwhelms agent context windows.
35. **Agent identity and reputation:** connect v1's `eas_reputation.py` and `agent_identity.py` to current on-chain agent registries (for example ERC-8004), so sellers have verifiable reputation.
36. **Before building this step, check what's current.** Agent standards change monthly. Spend half a day checking the latest x402, MCP, A2A and agent-payments specs and adjust the list.
37. Re-list everywhere: MCP Registry, Glama, Smithery, mcp.so, x402 Bazaar, PyPI (`aipaygen-mcp`), npm SDK, plus A2A directories.

**Done when:** a fresh agent (Claude, or a plain x402 client script) with no instructions can find a tool, pay and get a result from only the homepage URL. This is tested automatically in CI.

### Phase 6: Modern, polished design (for humans)
38. One design system: dark-first, clean type, motion only where it helps. Light mode works too. Fully mobile-friendly.
39. Pages: Home (what it is, live stats, "try it" box), Marketplace (search, filters, agent pages with live price, rating and code snippet), Sell (onboarding), Pricing, Docs, Course and Products, Status.
40. Every agent page shows copy-paste snippets for MCP, curl, Python and JS, including the x402 flow.
41. Live counters (calls served, agents, paying wallets) come from real data, never invented.
42. Accessibility (WCAG AA) and performance budget (Lighthouse 95+).

**Done when:** Lighthouse 95+ on all key pages and an accessibility scan passes.

### Phase 7: "Fool-proof" operations
Nothing is literally 100% fool-proof. What we can do is make failures rare, visible and recoverable. Concretely:
43. **Health checks and uptime monitors** on every core route and each payment path, alerting to your phone.
44. **Error tracking** (Sentry or similar) for the Worker and Python.
45. **Staging environment** (`staging.aipaygen.com`, testnet only) where every change is deployed and tested before production.
46. **CI/CD:** tests, scanners and e2e payment tests must pass. Production deploys come only from `main`, with one-click rollback.
47. **Kill switch:** one setting pauses all paid calls (refund-safe) if something goes wrong.
48. **Spending caps** on AI provider keys so a bug can't run up a bill.
49. **Runbook:** what to do if payments fail, the site goes down or a key leaks.

### Phase 8: Cutover
50. Run the full checklist on staging: every phase's "done when" check.
51. Switch aipaygen.com to the new edge with Site Intel routes unchanged, so current paying agents don't break.
52. Watch closely for 72 hours. Keep the v2-only rollback ready.
53. Announce: relaunch posts, directory updates and changelog.

---

## Order and rough effort
| Phase | Effort | Can run in parallel with |
|---|---|---|
| 0 Protect | ~1 hour (you + me) | n/a |
| 1 Restore | 1 day | n/a |
| 2 Security | 3–5 days | 3 |
| 3 Data | 2–3 days | 2 |
| 4 Payments | 4–6 days | 5 |
| 5 Agent discovery | 3–4 days | 4, 6 |
| 6 Design | 4–6 days | 5 |
| 7 Ops | 2 days | throughout |
| 8 Cutover | 1 day + 72h watch | n/a |

## Needs from you
1. **Access to the Pi** (or you copy the database files off it): this is the only place the marketplace data exists.
2. **Hosting choice for the Python core:** I recommend a managed container host plus managed Postgres (about $20–50/month) over the Pi.
3. **Trading features:** keep as simulation-only (recommended), or drop them?
4. **Legal check** on marketplace fees and seller payouts before launch. Even non-custodial, one hour with a fintech lawyer is worth it.
5. Approval of this plan, or changes to it.
