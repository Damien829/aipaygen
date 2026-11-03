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

12. **Tests write into the live databases:** the test suite uses the real DB paths, so the 2026-03-30 snapshot has 4,243 fake "credited" deposits ($168,195, keys `apk_test…`, sender `0xSENDER`). Tests must use temporary databases only, and the fake rows get removed before migration.
13. **AI calls went through a personal Claude Max subscription** (`claude -p`, per `docs/history/KNOWLEDGE_BASE.md`). Anthropic's terms don't allow a consumer subscription to power a paid service. Use API keys only, with spending caps (step 48).
14. **`trading-system` (Alpha Scout) connects to Robinhood with real credentials** in its `.env`. It isn't part of the rebuild. Keep it offline and rotate its credentials with everything else.

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

> ✅ **Done 2026-10-30.** The Pi's SD card held `aipaygen-transfer.tar.gz` (2026-03-30, confirmed as the final data). It's copied to `~/AIPayGen-Backups/` with a matching checksum. 39 databases pass integrity checks, unmerged journals are folded in, and the row counts (90 tables, 173,811 rows) are in `row-counts-2026-03-30.tsv`. Tag `v2-sitesintel-final`, branch `rebuild`.

### Phase 1: Bring v1 back into the repo
5. Put v1 under `core/` (the Python service) next to v2's `src/` (the edge Worker). Keep history with `git checkout 36370d3 -- <paths>` into the new layout.
6. Delete the committed logs (`requests.jsonl`, `update.log.old`, `.restart.lock`) and the Pi-only scripts (`tunnel-watchdog.sh`, `auto-update.sh`, `*.service.new`). Tighten `.gitignore`.
7. Run v1's 59 test files as they are and record the baseline (pass/fail counts) before changing anything.

**Done when:** v1 boots locally from `core/` and the baseline is recorded.

> ✅ **Done 2026-10-30.** v1 is restored under `core/` from `36370d3` (git history kept). Three marketplace pages and the knowledge base were in the archive but never in git, so they've been added (`core/docs/history/`).
> - **The last v1 commit didn't start.** Four files created on the Pi on Apr 1–3 were never committed: `sla_monitor.py`, `status_enterprise.html`, `market_success.html` and `teams.py`. The status routes now return 503 and post-purchase redirects to the agent page, until Phases 6–7 rebuild them.
> - **Boot check:** 565 routes; `/`, `/market`, `/pricing`, `/llms.txt`, `/openapi.json` and `/.well-known/x402` return 200.
> - **Test baseline** (Python 3.11, exact `requirements.lock`, no API keys): **1,460 passed, 5 failed**.
>   - `test_discovery_api::test_wallet_analytics_unknown_wallet`: missing `wallet_transactions` table
>   - `test_sse_negotiation` ×2: `/research` and `/write` return 400 without SSE header
>   - `test_v2_integration::test_buy_credits_*` ×2: buy-credits returns 402 instead of 200
> - **Found for Phase 2:** importing `app` starts the live scheduler (settlements, trading strategies, renewals), so tests and scripts run real background jobs.

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

> 🔶 **In progress. Done 2026-10-30:**
> - **SSRF (step 14):** new `security.guarded_http` checks every outbound address at connect time, so redirects and DNS rebinding can't reach private, loopback, link-local, metadata or IPv4-mapped addresses. Proxies are refused. It's used by `routes/utility`, `routes/data`, `routes/marketplace`, `web`, `api_discovery` and `discovery_engine` (~40 fetches that took user or seller URLs), and `safe_fetch` now uses it too. `verify=False` is gone. 23 new tests (`tests/test_ssrf_guard.py`).
> - **`/code/run` and the MCP `run_python_code` are off** (503 / error, never charged, since x402 only settles 2xx). They ran customer Python as the server user behind a word blocklist. `CODE_RUN_ENABLED=1` turns them back on, but only once they run inside an isolated sandbox (Phase 4).
> - **17 crash bugs (undefined names) fixed:** the IP auto-ban logger, the browser 404 page, the seller allowlist warning, 4 meta routes missing `parse_json_from_claude`, and the MCP tools `compare_models`, `estimate_cost` and `suggest_tools`, which always crashed.
> - **Dependencies (step 8):** ~250 advisories across 26 packages patched. `PyPDF2` (abandoned) is replaced by `pypdf`. MCP stays on 1.30 (all its advisories fixed); 2.x comes with Phase 5. On Linux, production resolves with **zero known vulnerabilities**. Intel macOS can't install `cryptography` 49+, so local dev runs 48.0.1, with 3 certificate-chain/PKCS#7 advisories that v1 doesn't hit. `requirements.lock` picks per platform.
> - **Tests:** 1,483 passed, the same 5 baseline failures, no regressions.
>
> **Second pass, also 2026-10-30:**
> - **One job process:** each gunicorn worker used to start its own scheduler, so settlements, renewals and trading jobs ran in parallel (a double-payout risk). Web workers now never run jobs. `python run_scheduler.py` is the single job process (deploy exactly one).
> - **Data isolation:** every database and runtime file resolves through `AIPAYGEN_DATA_DIR` (`paths.py`, 75+ paths). Tests use a throwaway directory, and a test proves it. Scout stats now create their tables on a fresh deployment instead of crashing.
> - **Claude models:** `claude-haiku-5-5` / `claude-sonnet-5-5` / `claude-opus-5-5` at current prices ($0.10/$0.50, $2/$10, $4/$20 per M tokens). One place (`model_router.prepare_claude_request`) strips `temperature`/`top_p`/`top_k`, which these models reject; it keeps thinking off on Haiku and effort low on Sonnet and Opus, so small `max_tokens` budgets aren't spent on thinking. Responses are read from every text block, not `content[0]` (which can be a thinking block), and refusals raise `ClaudeRefusal` so the router falls back. All direct calls go through the app-wide wrapper, which applies the same rules.
> - **Step 9 (dynamic SQL):** all 28 sites audited. Every interpolated column or sort name already comes from a hard-coded allowlist or mapping, so no change was needed. The 13 MD5/SHA1 uses are cache keys, A/B buckets and a hash tool, now marked `usedforsecurity=False`. Bandit high-severity findings: **0**.
> - **Step 12 (CORS):** it already used an allowlist (the audit overstated this). Localhost origins are now dev-only (`AIPAYGEN_DEV=1`), `Vary: Origin` is added so Cloudflare can't cache one site's CORS answer for another, and the x402 v2 headers are allowed and exposed. **Step 13:** HSTS preload, `X-Frame-Options`, `nosniff`, `Referrer-Policy` and `Permissions-Policy` were already set. The page CSP still allows inline script and `eval`; fixing that needs nonces in all 63 templates, so it moves to Phase 6.
> - **Step 17 (logs):** the one full API key in a log (`crypto_poller`) is masked. IP hashes use HMAC with `AIPAYGEN_IP_HASH_SECRET`, since plain SHA-256 of an IPv4 address is reversible; without the secret they fall back to the v1 hash so existing trial-abuse records still match.
> - **Step 18 (CI):** `.github/workflows/ci.yml` (actions pinned to commit SHAs) runs core tests, pip-audit, Bandit (high), the undefined-name lint, Worker typecheck/tests/npm audit, and gitleaks over full history. The 5 baseline failures are deselected so any new failure fails CI. The old `core/.github` workflows (which never ran, and whose `publish.yml` would have pushed v1's `aipaygen-mcp` 1.9.5 over 2.0.0) are removed.
> - **Live v2 Worker:** a high-severity `zod` advisory was patched (`npm audit fix`, 68/68 tests). **Not deployed yet.**
> - **Tests:** 1,495 passed, the same 5 baseline failures.
>
> **Third pass, also 2026-10-30:**
> - **Step 15 (webhooks):** both outbound systems now send `X-Webhook-Signature-V2: t=<unix>,v1=HMAC-SHA256(secret, "<t>.<body>")`, freshly signed per attempt so receivers can reject replays older than 5 minutes (`security.verify_webhook_signature`). `webhook_dispatch` had no signing at all and **sent the customer's full API key in every body**: the key is now masked, each webhook gets its own secret (shown once at registration), and webhooks registered before this go unsigned until re-registered. Both use the SSRF-safe client (`routes/webhooks.py` had been missed). Inbound Stripe was already correct: fails closed, verified, deduplicated.
> - **Step 10, app side (admin):** with `CF_ACCESS_TEAM_DOMAIN` + `CF_ACCESS_AUD` set, every `/admin` page, every `require_admin` route and the admin secret used as an API key also need a valid Cloudflare Access JWT (RS256, audience, issuer and expiry checked against Cloudflare's published keys). `ADMIN_REQUIRE_CF_ACCESS=1` fails closed until it's configured. The admin-secret check in `require_api_key` is now timing-safe. 8 tests.
> - **Tests:** 1,506 passed, the same 5 baseline failures. Bandit high: 0.
>
> **Still open in Phase 2:**
> - **Step 10, dashboard side (owner):** in Cloudflare Zero Trust, add an Access application for `aipaygen.com/admin*` (and the admin API paths), with your email and a second factor. Copy its team domain and Application Audience (AUD) tag into `CF_ACCESS_TEAM_DOMAIN` / `CF_ACCESS_AUD`, then set `ADMIN_REQUIRE_CF_ACCESS=1`.
> - **Step 11:** move secrets and rotate every key (**owner action**). New: set `AIPAYGEN_IP_HASH_SECRET`.
> - **Step 16:** edge rate limits (with Phase 4).
> - **Push:** the `rebuild` branch can't be pushed until the GitHub login has the `workflow` scope (`gh auth refresh -h github.com -s workflow`, then press Enter in that terminal).
> - **Decide:** moving the Anthropic SDK 0.84 → 2.x switches the API version to `2026-10-21`. The current models already ignore `temperature`, so this is mostly mechanical.
> - **Unverified:** gitleaks is untested until the first CI run; it may flag test fixtures that need an allowlist.

### Phase 3: Data layer

> ♻️ **Changed 2026-10-30: $0/month, SQLite stays.** The owner wants no paid services, and a Postgres port turned out to mean rewriting 1,050 queries across 52 modules (weeks, high risk). Phase 3 is now: **SQLite on one Oracle Always Free server, with Litestream streaming every change to Cloudflare R2** (point-in-time restore for 7 days). Cloudflare Tunnel is the only way in. Postgres can come later, money tables first, if traffic ever needs it. Steps 19–21 below are the original plan, kept for reference.
>
> ✅ **Built 2026-10-30 (not deployed):**
> - `core/scripts/clean_v1_snapshot.py` copies the snapshot and removes **30,266** test rows by exact rules, written to `cleanup-report.json`: 4,243 fake deposits, 4 test keys, 1,587 scout test conversions, and 25,000+ rows pointing at keys that don't exist. `billing_audit` is left untouched. Integrity is OK and the source is unchanged. Result: `~/AIPayGen-Backups/v1-data-cleaned-2026-10-30`, with 143,545 rows kept, including all 72 listings, 61 reviews, 954 agents, 4,379 APIs, 4,989 skills, 1,509 services and 50 posts.
> - **Finding:** the snapshot has **no real paying-customer records**. Every deposit is fake and every API key was created by a test (tests also ran `DROP TABLE` on live data). Your own account is kept, but needs a new key.
> - **Deploy setup** (`deploy/`): `compose.yaml` runs restore → web + scheduler (exactly one) + mcp + litestream + tunnel. `litestream.yml` lists all 46 databases, and `tests/test_backups_cover_all_dbs.py` fails if a new one is missing. Also `restore.sh`, `.env.example` and `README.md` (setup, everyday commands, restores). The core `Dockerfile` installs from the lock and runs as non-root; `gunicorn.conf.py` no longer uses Pi paths and logs to stdout.
> - **Verified locally:** the gunicorn config check passes, and v1 on the cleaned real data serves `/`, `/market`, `/pricing`, `/skills`, `/llms.txt`, `/openapi.json`, `/.well-known/*` and `/health` with 200s.
> - **Fixed:** the fonts and app assets route had been pointed at the data folder in the Phase 2 path change; a test now covers it.
> - **Not verified:** Docker isn't installed on this Mac, so the image build, compose run and Litestream config are untested until the server's first `docker compose up`.
> - **Owner steps:** authorize this Mac's key on the Oracle server, create the R2 bucket and token, and create the Tunnel token (`deploy/README.md` steps 1–3).
19. Move ~30 SQLite files into **one managed Postgres** with migrations (Alembic). Each old file becomes its own schema so the migration stays mechanical.
20. Write a migration script that loads the Phase 0 backups. Run it twice, verify that row counts and money totals match exactly, and keep it repeatable.
21. Turn on daily automated backups with point-in-time recovery and run a **monthly restore test**.

**Done when:** a restore from backup gives the same balances.

### Phase 4: One payment layer, done right

> 🔶 **In progress. Done 2026-10-30 (not deployed):**
> - **Step 22:** `pricing/core-routes.json` holds the 178 prices v1 actually charged (app.py + route_pricing.py + the data default, merged by `core/scripts/export_pricing.py`). It's now the one table, and the Worker reads it.
> - **Step 23:** the Worker answers everything it doesn't serve itself by forwarding to the core (`src/core/proxy.ts`). Priced routes go through the Worker's mainnet-tested `chargeAndRun` (credits or x402 → verify → core runs → settle only on 2xx; 4xx/5xx is never charged). Every forward is HMAC-signed (ts, method, raw path, body hash, paid, client IP), and `core/edge_auth.py` rejects anything else with 401 when `AIPAYGEN_EDGE_SECRET` is set. Signed requests skip v1's own x402 and key-billing wrappers, so nothing is charged twice. A shared test vector proves the TS and Python signatures match. Bazaar metadata now uses each route's real method.
> - **Step 24 (partly):** charge-on-success comes from `chargeAndRun`. Idempotency keys are still open.
> - **Found:** two of the 5 baseline failures (`test_buy_credits_*`) expect 200 from `/credits/buy`, which is priced at $5, so 402 is correct. Those tests are wrong, not the code.
> - **Limits:** streaming routes (`/stream/*`, `/agent/stream`) are buffered for now. Shared paths (`/`, `/llms.txt`, `/openapi.json`, `/sitemap.xml`) stay with the Worker until Phase 5 merges discovery. Core features keyed to v1 `apk_` keys keep working; Worker `apg_` keys pay.
> - **Step 25 (replay):** a verified x402 payment is claimed in D1 (`payment_claims`, migration 0002) before the tool runs. A second copy gets 409 `PAYMENT_ALREADY_USED`, and the claim is released if the run or the settlement fails, so an honest retry still works. **Deploy needs** `npm run db:migrate:remote` before the new Worker goes live.
> - **Next session, in order:** (1) a test for the claim path with a D1 stub; (2) step 24, `Idempotency-Key` for credit calls; (3) step 26, seller payouts paid straight to the seller's wallet (`payTo` = seller, fee as a second requirement), retiring custodial settlement; (4) step 27, Solana (`@x402/svm`); (5) step 29, nightly on-chain vs `usage` reconciliation; (6) step 30, Base Sepolia end-to-end through `/research` with `scripts/x402-pay-test.mjs`.
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

> 🔎 **Research update 2026-10-30** (re-check before each phase):
> - **x402:** v2 is current, run by the x402 Foundation under the Linux Foundation, with Coinbase, Cloudflare, Visa and Google. Schemes: `exact`, `upto` and `batch-settlement`. **Use `upto` for AI tools**, where the price depends on tokens used (charge up to a cap, settle the actual amount), and `batch-settlement` for high-frequency agents. Networks are CAIP-2 (`eip155:*`, `solana:*`). `/verify` must not commit state; at least one verify or settle runs before work starts. Bazaar is the official discovery extension. v1 is on the Python SDK 2.3 (current 2.26), so Phase 4 moves all payments to the Worker anyway.
> - **MCP:** spec `2026-07-28` is current. It's stateless (no sessions or `Mcp-Session-Id`), with optional `server/discover`, a formal extensions framework, **Tasks** (long-running jobs, good for research and workflows) and **MCP Apps** (server-rendered UI), plus list caching and stronger auth. The v2 Worker already speaks it. **Decision:** the Worker becomes the single MCP endpoint (step 34), rather than porting v1's Python MCP server to SDK 2.x.
> - **A2A:** the agent card lives at **`/.well-known/agent-card.json`** (since v0.3). v1 only serves the old `/.well-known/agent.json`; serve both.
> - **Other payment rails:** **MPP** (Stripe + Tempo, launched 2026-03-18) does session-based streaming micropayments over stablecoins, cards and Lightning, and Stripe supports both MPP and x402. That's a cheap second rail via the Stripe account step 28 already needs. **AP2** (Google, v0.2), Visa TAP, Mastercard Agent Pay and Stripe ACP are the "identity-native" camp; publish AP2/ACP discovery so those agents can find us, and settle through x402 or Stripe.
> - **ERC-8004** (on-chain agent identity and reputation): live on mainnets but still a Draft EIP. Treat it as optional and add it behind a flag.
> - **AI models:** v1's model router names models that no longer exist (`claude-haiku`, `gpt-4o-mini`, ...). Update to the current families (Claude 5: Haiku 5.5 / Sonnet 5.5 / Opus 5.5 / Fable 5.1, plus current OpenAI and Gemini) in Phase 2, with the API-key-only rule (finding 13).
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

---

## Catch-up list (2026-11-03): everything started and not finished

Pivot since Phase 4: **Worker-first.** The marketplace runs on Cloudflare (free, scales automatically); the Python core is an optional back end.

### Done and live
- Marketplace in D1: 11,246 seed entries plus self-updating MCP Registry and x402 Bazaar ingest; full-text search; `search_marketplace` tool.
- Discovery: item pages and sitemaps, agent card, `/.well-known/x402`, `llms-full.txt`, AI-crawler robots.txt, WebMCP, markdown pages, `Link` headers.
- Word of mouth: share block, related items, agent self-registration, demand logging.
- Interactive marketplace (live search, filters, snippets).
- Cron every 10 min: agent refresh, health checks, MCP Registry and Bazaar ingest.

### Built, waiting for deploy approval
- Prices hidden (quote on request) · verified trust scores and ranking · Most Wanted page · A2A agent at `/a2a` · referral credits. Migrations 0006 and 0007.

### Code I can still do (in priority order)
1. ✅ Payment-claim tests (4, including parallel copies) in `test/charge-claims.test.ts`.
2. ✅ `Idempotency-Key` on credit calls (migration 0008): a retry returns the first result at $0; reuse for another tool is refused.
3. ✅ Free first calls (migration 0009): 3 a day per caller (hashed IP) on tools up to $0.005, independent of the facilitator.
4. ❌ Not publishing v1's 50 blog posts (auto-generated around trending HN titles; Google's scaled-content policies could hurt the real marketplace pages) or its 10 agent-builder templates (the builder isn't running). Both stay in the backup.
5. Reconciliation: nightly comparison of on-chain receipts with the `usage` table (step 29).
6. Solana payments (`@x402/svm`, step 27).
7. Fix or retire the 5 old core test failures (2 are wrong tests: the $5 credit pack correctly returns 402).
8. Won't fix for now: registering our own card fails with 530 (Cloudflare blocks a Worker fetching its own zone). No real agent hits this.

### Needs you
- **GitHub `workflow` permission:** unlocks pushing, CI, Dependabot and auto-deploy.
- **Cloudflare API token** as a GitHub secret (auto-deploy). **Cloudflare Access** app for `/admin`.
- **Rotate every key** from the old Pi. Set `AIPAYGEN_IP_HASH_SECRET`, plus `ADMIN_TOKEN` on the Worker for `/admin/*`.
- **Oracle account recovery** (only for the optional Python core) and **R2 or Oracle storage** for its backups.
- **Testnet end-to-end payment test** (step 30): fund the test wallet with Base Sepolia USDC.
- **Directory listings:** `docs/LISTINGS.md` (MCP Registry, Smithery, Glama, PulseMCP, search consoles).
- **Legal check** before pay-through routing or seller payouts (below).

## Pay-through routing (planned, not built)

**Goal:** an agent calls any listed x402 service through AIPayGen with one `apg_` key or wallet, and AIPayGen takes a small fee.

**Why it's not built yet:** charging the agent and paying the provider later means AIPayGen holds other people's money. That's money transmission in the US (FinCEN rules and state licenses) and similar rules elsewhere. **Get a fintech lawyer's view first.**

**Non-custodial versions that avoid holding funds:**
1. **Relay only:** AIPayGen forwards the call and the provider's 402 quote; the agent's own wallet pays the provider directly. AIPayGen charges its own separate, small x402 fee for the routing (two payments, each to its real recipient). No custody.
2. **Facilitator partnership:** route through a licensed facilitator (for example Coinbase CDP) that handles settlement and splits.
3. **Credits only for AIPayGen's own tools,** as today.

Recommended order: (1) relay only first, since it's legal-light and immediately useful; (2) after legal advice.
