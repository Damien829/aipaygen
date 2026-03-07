# Platform Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform AiPayGen from a raw API into a commercial AI agent platform — polished website, paid-by-default pricing, competitive protection, and access-controlled discovery.

**Architecture:** All changes are in `app.py` (monolith with inline HTML templates). Five workstreams executed in dependency order: pricing restructure → competitive protection → discovery layer updates → access control → website overhaul. Each workstream modifies inline template strings, route handlers, or service definitions within `app.py`.

**Tech Stack:** Flask, Jinja2 (render_template_string), x402 middleware, SQLite, IBM Plex fonts, inline CSS

---

## Workstream A: Pricing Restructure (Tasks 1–3)

Move data endpoints from free to paid. Keep only honeypot endpoints free.

### Task 1: Move data endpoints to paid tier

**Files:**
- Modify: `app.py:3899-4080` (`_build_discover_services()`)
- Modify: `app.py` (data endpoint routes — `/data/*`)
- Test: `tests/test_pricing.py`

**Step 1: Write the failing test**

Create `tests/test_pricing.py`:

```python
"""Tests for pricing restructure — data endpoints are paid, honeypots are free."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__) + "/..")

def test_free_tier_only_honeypots():
    """Only specific honeypot endpoints should be free ($0.00)."""
    from app import _build_discover_services
    categories = _build_discover_services()
    all_services = [s for cat in categories.values() for s in cat]

    FREE_ALLOWED = {
        "/preview", "/free/time", "/free/uuid", "/free/ip",
        "/free/hash", "/free/base64", "/free/random",
        "/health", "/.well-known/agent.json", "/llms.txt",
    }

    for svc in all_services:
        if svc["price_usd"] == 0:
            assert svc["endpoint"] in FREE_ALLOWED, \
                f"{svc['endpoint']} should not be free"


def test_data_endpoints_are_paid():
    """Data endpoints (weather, crypto, stocks, etc.) must cost >= $0.01."""
    from app import _build_discover_services
    categories = _build_discover_services()
    data_services = categories.get("Data & Utilities", [])

    for svc in data_services:
        if svc["endpoint"].startswith("/free/"):
            continue
        assert svc["price_usd"] >= 0.01, \
            f"{svc['endpoint']} should be paid, got ${svc['price_usd']}"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pricing.py -v`
Expected: FAIL — many data endpoints currently have `price_usd: 0`

**Step 3: Update `_build_discover_services()` pricing**

In `app.py`, find `_build_discover_services()` (line 3899). For every service entry in the Data & Utilities category that has `"price_usd": 0.00` (weather, crypto, stocks, jokes, quotes, news, wikipedia, arxiv, github-trending, reddit, youtube-transcript, etc.), change to `"price_usd": 0.01`.

Keep `price_usd: 0.00` ONLY for:
- `/preview`
- `/free/time`, `/free/uuid`, `/free/ip`, `/free/hash`, `/free/base64`, `/free/random`
- `/health`

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pricing.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_pricing.py app.py
git commit -m "feat: move data endpoints to paid tier ($0.01 each)"
```

---

### Task 2: Remove explicit pricing from public templates

**Files:**
- Modify: `app.py:4083-4176` (DISCOVER_HTML template)
- Modify: `app.py:4343-4542` (LLMS_TXT)

**Step 1: Update DISCOVER_HTML — remove per-endpoint dollar amounts**

In the DISCOVER_HTML template (line ~4155-4157), replace the price display:

Old:
```html
<div class="price {% if svc.price_usd == 0 %}price-free{% else %}price-paid{% endif %}">
  {% if svc.price_usd == 0 %}FREE{% else %}${{ "%.2f"|format(svc.price_usd) }} USDC{% endif %}
</div>
```

New:
```html
<div class="price {% if svc.price_usd == 0 %}price-free{% else %}price-paid{% endif %}">
  {% if svc.price_usd == 0 %}FREE{% else %}Pay-per-use via x402{% endif %}
</div>
```

**Step 2: Update LLMS_TXT — remove price column from tables**

In the `LLMS_TXT` string (line 4343), remove the `Price` column from all tables. Replace `| Endpoint | Price | Input | Output |` with `| Endpoint | Input | Output |` and remove per-row dollar amounts. Keep endpoint names, inputs, and outputs only.

Also remove the line `"140+ Claude-powered endpoints"` — replace with "Claude-powered AI endpoints".

**Step 3: Verify templates render without errors**

Run: `python -c "from app import app; app.test_client().get('/discover', headers={'Accept': 'text/html'})" `
Expected: No error

**Step 4: Commit**

```bash
git add app.py
git commit -m "feat: remove explicit pricing from public-facing templates"
```

---

### Task 3: Update DISCOVER_HTML stats to hide service count

**Files:**
- Modify: `app.py:4129-4136` (DISCOVER_HTML header stats)

**Step 1: Remove exact service count from stats section**

Replace the stats section in DISCOVER_HTML:

Old:
```html
<div class="stats">
  <div class="stat"><div class="num">{{ total }}</div><div class="label">Services</div></div>
  <div class="stat"><div class="num">{{ free_count }}</div><div class="label">Free</div></div>
  <div class="stat"><div class="num">{{ categories|length }}</div><div class="label">Categories</div></div>
</div>
```

New:
```html
<div class="stats">
  <div class="stat"><div class="num">{{ categories|length }}</div><div class="label">Categories</div></div>
  <div class="stat"><div class="num">x402</div><div class="label">Pay-per-use</div></div>
  <div class="stat"><div class="num">USDC</div><div class="label">On Base</div></div>
</div>
```

**Step 2: Commit**

```bash
git add app.py
git commit -m "feat: replace service counts with category descriptions in discover page"
```

---

## Workstream B: Competitive Protection (Tasks 4–5)

### Task 4: Strip input/output schemas from public discovery JSON

**Files:**
- Modify: `app.py:4179-4221` (discover route)
- Test: `tests/test_discover.py` (add test)

**Step 1: Write the failing test**

Add to `tests/test_web.py` (or create `tests/test_discover.py`):

```python
"""Tests for /discover competitive protection."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__) + "/..")

def test_discover_json_no_schemas():
    """Public /discover JSON must not expose input/output schemas."""
    from app import app
    client = app.test_client()
    resp = client.get("/discover", headers={"Accept": "application/json"})
    data = json.loads(resp.data)

    for cat_name, services in data["categories"].items():
        for svc in services:
            assert "input" not in svc, \
                f"{svc['endpoint']} leaks input schema"
            assert "output" not in svc, \
                f"{svc['endpoint']} leaks output schema"


def test_discover_json_no_exact_prices():
    """Public /discover JSON must not expose exact USD prices."""
    from app import app
    client = app.test_client()
    resp = client.get("/discover", headers={"Accept": "application/json"})
    data = json.loads(resp.data)

    for cat_name, services in data["categories"].items():
        for svc in services:
            assert "price_usd" not in svc, \
                f"{svc['endpoint']} leaks exact price"


def test_discover_json_has_endpoint_and_description():
    """Public /discover JSON still has endpoint name, method, description."""
    from app import app
    client = app.test_client()
    resp = client.get("/discover", headers={"Accept": "application/json"})
    data = json.loads(resp.data)

    for cat_name, services in data["categories"].items():
        for svc in services:
            assert "endpoint" in svc
            assert "description" in svc
            assert "method" in svc
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discover.py -v`
Expected: FAIL — current JSON includes input, output, price_usd

**Step 3: Strip schemas and prices from discover JSON response**

In `app.py` at the `discover()` route (line ~4201-4221), before returning JSON, strip sensitive fields:

```python
# Strip schemas and exact prices for competitive protection
stripped_categories = {}
for cat_name, services in categories.items():
    stripped_categories[cat_name] = [
        {
            "endpoint": s["endpoint"],
            "method": s["method"],
            "description": s["description"],
            "pricing": "free" if s.get("price_usd", 0) == 0 else "x402",
        }
        for s in services
    ]
```

Replace `"categories": categories` with `"categories": stripped_categories` in the JSON response. Also remove `total_services` and `free_count` from `meta`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_discover.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app.py tests/test_discover.py
git commit -m "feat: strip schemas and exact prices from /discover JSON"
```

---

### Task 5: Strip source attribution from skills search

**Files:**
- Modify: `app.py:8922-8930` (search_skills route)
- Test: `tests/test_discover.py` (add test)

**Step 1: Write the failing test**

```python
def test_skills_search_no_source_attribution():
    """Skills search must not reveal where skills were harvested from."""
    from app import app
    client = app.test_client()
    resp = client.get("/skills/search?q=python")
    data = json.loads(resp.data)

    for skill in data.get("results", []):
        assert "source" not in skill, \
            f"Skill '{skill.get('name', '?')}' leaks source attribution"
        assert "source_url" not in skill, \
            f"Skill '{skill.get('name', '?')}' leaks source_url"
        assert "harvested_from" not in skill, \
            f"Skill leaks harvested_from"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discover.py::test_skills_search_no_source_attribution -v`

**Step 3: Strip source fields from skills search results**

In `search_skills()` (line 8930), after getting results, strip attribution:

```python
STRIP_FIELDS = {"source", "source_url", "harvested_from", "origin", "crawled_from"}
results = [
    {k: v for k, v in r.items() if k not in STRIP_FIELDS}
    for r in _skills_engine.search(q, top_n=min(top_n, 50))
]
return jsonify({"query": q, "results": results})
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_discover.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app.py tests/test_discover.py
git commit -m "feat: strip source attribution from skills search results"
```

---

## Workstream C: Agent Discovery Layer (Tasks 6–8)

### Task 6: Update agent.json — remove pricing breakdown and service count

**Files:**
- Modify: `app.py:5514-5630` (agent_manifest route)
- Test: `tests/test_discover.py`

**Step 1: Write the failing test**

```python
def test_agent_json_no_pricing_breakdown():
    """agent.json must not expose detailed pricing tiers."""
    from app import app
    client = app.test_client()
    resp = client.get("/.well-known/agent.json")
    data = json.loads(resp.data)

    pricing = data.get("pricing", {})
    # Should just say "x402" — no specific dollar amounts or tier details
    assert "free_tier" not in pricing or "10" not in str(pricing.get("free_tier", ""))
    assert "$5" not in str(pricing)

    # Should not mention exact endpoint counts
    desc = data.get("description", "")
    assert "140+" not in desc
    assert "138+" not in desc


def test_agent_json_has_capabilities():
    """agent.json still lists capabilities and payment method."""
    from app import app
    client = app.test_client()
    resp = client.get("/.well-known/agent.json")
    data = json.loads(resp.data)

    assert "skills" in data
    assert "x402" in str(data.get("authentication", {})) or \
           "x402" in str(data.get("pricing", {}))
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discover.py::test_agent_json_no_pricing_breakdown -v`
Expected: FAIL — current description has "140+" and pricing has "10 AI calls/day"

**Step 3: Update agent_manifest()**

In `app.py` line 5518-5630, update:

1. Replace description: remove "140+ endpoints" → "AI agent API marketplace with research, writing, coding, analysis, web scraping, real-time data, file storage, and agent infrastructure. Pay in USDC on Base via x402."

2. Replace pricing section:
```python
"pricing": {
    "method": "x402",
    "currency": "USDC",
    "network": "Base Mainnet",
    "discovery": "Send any request — receive x402 payment instructions in 402 response",
},
```

3. In `data` skill (id="data"), change description: remove "Free" from the beginning: "Real-time weather, crypto, stocks, news, Wikipedia, arXiv, GitHub trending, Reddit, YouTube transcripts"

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_discover.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app.py tests/test_discover.py
git commit -m "feat: slim down agent.json — remove pricing breakdown and service counts"
```

---

### Task 7: Slim down llms.txt

**Files:**
- Modify: `app.py:4343-4542` (LLMS_TXT string)

**Step 1: Rewrite LLMS_TXT to capabilities overview**

Replace the entire LLMS_TXT string. Keep:
- Service name and description (no exact endpoint count)
- Payment protocol section (x402, USDC, Base)
- Category listing (just category names + brief descriptions, NOT per-endpoint tables)
- Quick start code example
- Free endpoint list (but only honeypots)
- MCP integration section

Remove:
- All pricing tables with dollar amounts
- Input/output schema details
- Model pricing table
- Implementation details competitors could copy

The new LLMS_TXT should be ~80 lines max (currently ~200).

**Step 2: Verify it serves correctly**

Run: `python -c "from app import app; print(app.test_client().get('/llms.txt').data.decode()[:200])"`
Expected: Shows the new slimmed-down header

**Step 3: Commit**

```bash
git add app.py
git commit -m "feat: slim llms.txt to capabilities overview, remove implementation details"
```

---

### Task 8: Update robots.txt

**Files:**
- Modify: `app.py:4325-4340` (robots_txt route)

**Step 1: Update robots.txt to block internal routes**

Update the `robots_txt()` function to return:

```text
User-agent: *
Allow: /
Allow: /discover
Allow: /llms.txt
Allow: /.well-known/agent.json
Disallow: /admin/
Disallow: /stats
Disallow: /skills/
Disallow: /discovery/
Disallow: /outbound/
Disallow: /harvest/
Disallow: /agent
Disallow: /credits/
Disallow: /free-tier/

Sitemap: https://api.aipaygen.com/sitemap.xml
```

**Step 2: Commit**

```bash
git add app.py
git commit -m "feat: update robots.txt to block internal routes from crawlers"
```

---

## Workstream D: Access Control (Tasks 9–10)

### Task 9: Add auth to /skills/search

**Files:**
- Modify: `app.py:8922-8930` (search_skills route)
- Test: `tests/test_discover.py`

**Step 1: Write the failing test**

```python
def test_skills_search_requires_auth():
    """GET /skills/search requires admin auth or x402 payment."""
    from app import app
    client = app.test_client()
    resp = client.get("/skills/search?q=python")
    assert resp.status_code in (401, 402), \
        f"Expected 401/402, got {resp.status_code}"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discover.py::test_skills_search_requires_auth -v`
Expected: FAIL — currently returns 200

**Step 3: Add @require_admin decorator to search_skills()**

In `app.py` line 8922, add the `@require_admin` decorator:

```python
@app.route("/skills/search", methods=["GET"])
@require_admin
def search_skills():
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_discover.py::test_skills_search_requires_auth -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app.py tests/test_discover.py
git commit -m "feat: require admin auth for /skills/search endpoint"
```

---

### Task 10: Rate-limit /discover JSON to names+descriptions only for unauthenticated

Already done in Task 4 (stripped schemas from JSON response). No additional work needed — the stripped response IS the rate-limited discovery. Mark complete.

---

## Workstream E: Website Overhaul (Tasks 11–14)

### Task 11: Create shared nav + footer component strings

**Files:**
- Modify: `app.py` (add NAV_HTML and FOOTER_HTML constants before LANDING_HTML)

**Step 1: Create NAV_HTML constant**

Add above LANDING_HTML (before line 2065):

```python
NAV_HTML = '''
<nav style="position:fixed;top:0;width:100%;z-index:100;background:rgba(2,4,8,0.92);backdrop-filter:blur(12px);border-bottom:1px solid rgba(0,255,157,0.08);padding:14px 0">
  <div style="max-width:1200px;margin:0 auto;padding:0 24px;display:flex;align-items:center;justify-content:space-between">
    <a href="/" style="font-family:\'IBM Plex Mono\',monospace;font-size:1.3rem;font-weight:700;color:#fff;text-decoration:none">Ai<span style="color:#00ff9d">Pay</span>Gent</a>
    <div style="display:flex;gap:24px;align-items:center">
      <a href="/discover" style="color:#8b949e;text-decoration:none;font-family:\'IBM Plex Sans\',sans-serif;font-size:0.9rem;transition:color .2s">Discover</a>
      <a href="/docs" style="color:#8b949e;text-decoration:none;font-family:\'IBM Plex Sans\',sans-serif;font-size:0.9rem;transition:color .2s">Docs</a>
      <a href="/preview" style="color:#00ff9d;text-decoration:none;font-family:\'IBM Plex Sans\',sans-serif;font-size:0.9rem;font-weight:600">Try Free</a>
    </div>
  </div>
</nav>
'''

FOOTER_HTML = '''
<footer style="border-top:1px solid rgba(0,255,157,0.08);padding:40px 24px;text-align:center;background:#020408">
  <div style="max-width:1200px;margin:0 auto">
    <div style="margin-bottom:16px">
      <a href="/discover" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Discover</a>
      <a href="/docs" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Docs</a>
      <a href="/llms.txt" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">llms.txt</a>
      <a href="/.well-known/agent.json" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">agent.json</a>
      <a href="/health" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Health</a>
    </div>
    <div style="color:#4a5568;font-size:0.8rem;font-family:\'IBM Plex Mono\',monospace">
      Powered by x402 &middot; USDC on Base &middot; Built for autonomous agents
    </div>
  </div>
</footer>
'''
```

**Step 2: Commit**

```bash
git add app.py
git commit -m "feat: add shared NAV_HTML and FOOTER_HTML component strings"
```

---

### Task 12: Refresh homepage (LANDING_HTML)

**Files:**
- Modify: `app.py:2065-2982` (LANDING_HTML)

**Step 1: Rewrite LANDING_HTML**

Replace the entire LANDING_HTML string. The new version should:

1. Keep the existing dark theme (--bg: #020408, --green: #00ff9d, IBM Plex fonts)
2. Use `NAV_HTML` and `FOOTER_HTML` (inject via `{{ nav }}` and `{{ footer }}`)
3. Hero section: animated tagline "AI Infrastructure for the Agent Economy", subheading "Pay-per-use AI endpoints. No API keys. Pay USDC on Base via x402.", CTA button → /discover
4. Three value prop cards:
   - "AI-Powered Tools" — Research, write, code, analyze with Claude
   - "x402 Native" — No accounts, no API keys. Just pay and go.
   - "Agent Memory" — Persistent memory, messaging, task boards
5. "How it works" section: 3 steps (Call endpoint → Get 402 response → Pay & receive)
6. Remove exact service counts (no "140+" or "138+")
7. Social proof section: "Used by autonomous agents worldwide" (generic, no fake numbers)
8. Remove links to /buy-credits, /blog, /sdk from nav (per YAGNI — focus on /discover, /docs)

**Step 2: Update landing() route to pass nav/footer**

```python
@app.route("/")
def landing():
    from flask import make_response
    resp = make_response(render_template_string(LANDING_HTML, nav=NAV_HTML, footer=FOOTER_HTML))
    resp.headers["Link"] = '</llms.txt>; rel="llms-txt"'
    return resp
```

**Step 3: Test homepage renders**

Run: `python -c "from app import app; r = app.test_client().get('/'); print(r.status_code, len(r.data))"`
Expected: `200` with non-zero content length

**Step 4: Commit**

```bash
git add app.py
git commit -m "feat: refresh homepage with value props and x402 flow section"
```

---

### Task 13: Redesign /discover page

**Files:**
- Modify: `app.py:4083-4177` (DISCOVER_HTML)
- Modify: `app.py:4179-4221` (discover route)

**Step 1: Rewrite DISCOVER_HTML**

Replace DISCOVER_HTML with new design:

1. Match homepage dark theme (--bg: #020408, --green: #00ff9d, IBM Plex fonts)
2. Use `{{ nav }}` and `{{ footer }}`
3. Add a search/filter bar at the top (client-side JS filtering by name/description)
4. Category tabs (horizontal pills) instead of vertical sections
5. Service cards show: endpoint name, method badge, description, "Free" or "x402" label (no dollar amounts)
6. Cards should NOT link to raw JSON or show input/output schemas
7. Remove "Try Free Preview" and "OpenAPI Spec" CTA buttons from header
8. Add a single CTA: "Read the Docs →" linking to /docs

**Step 2: Update discover() route to pass nav/footer**

```python
@app.route("/discover")
def discover():
    categories = _build_discover_services()
    base_url = "https://api.aipaygen.com"
    all_services = [s for cat_services in categories.values() for s in cat_services]

    best = request.accept_mimetypes.best_match(
        ["text/html", "application/json"], default="application/json"
    )

    if best == "text/html":
        # Strip schemas for HTML too — only show name, method, description, pricing tier
        display_categories = {}
        for cat_name, services in categories.items():
            display_categories[cat_name] = [
                {
                    "endpoint": s["endpoint"],
                    "method": s["method"],
                    "description": s["description"],
                    "free": s.get("price_usd", 0) == 0,
                }
                for s in services
            ]
        return render_template_string(
            DISCOVER_HTML,
            categories=display_categories,
            nav=NAV_HTML,
            footer=FOOTER_HTML,
        )

    # JSON response (already stripped in Task 4)
    stripped_categories = {}
    for cat_name, services in categories.items():
        stripped_categories[cat_name] = [
            {
                "endpoint": s["endpoint"],
                "method": s["method"],
                "description": s["description"],
                "pricing": "free" if s.get("price_usd", 0) == 0 else "x402",
            }
            for s in services
        ]

    return jsonify({
        "meta": {
            "name": "AiPayGen",
            "description": "AI agent API marketplace. Pay USDC on Base via x402.",
            "categories": list(categories.keys()),
        },
        "payment": {
            "wallet": WALLET_ADDRESS,
            "network": EVM_NETWORK,
            "payment_scheme": "x402/exact",
            "usdc_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        },
        "categories": stripped_categories,
        "links": {
            "openapi": f"{base_url}/openapi.json",
            "llms_txt": f"{base_url}/llms.txt",
            "docs": f"{base_url}/docs",
        },
    })
```

**Step 3: Test both HTML and JSON responses**

Run: `python -m pytest tests/test_discover.py -v`
Expected: All discover tests pass

**Step 4: Commit**

```bash
git add app.py
git commit -m "feat: redesign /discover with search, category tabs, no schema exposure"
```

---

### Task 14: Add /docs page

**Files:**
- Modify: `app.py` (add DOCS_HTML constant and /docs route)
- Test: `tests/test_discover.py`

**Step 1: Write the failing test**

```python
def test_docs_page_exists():
    """GET /docs returns HTML with integration guide."""
    from app import app
    client = app.test_client()
    resp = client.get("/docs")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "x402" in html
    assert "Quick Start" in html or "Getting Started" in html
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discover.py::test_docs_page_exists -v`
Expected: FAIL — no /docs route exists

**Step 3: Create DOCS_HTML and /docs route**

Add `DOCS_HTML` constant (after DISCOVER_HTML) with:

1. Same dark theme, nav, footer
2. Sections:
   - **Getting Started**: What AiPayGen is, how x402 works (3-step flow)
   - **x402 Payment Flow**: Code example showing POST → 402 → retry with payment header
   - **MCP Integration**: `pip install aipaygen-mcp` + `claude mcp add` instructions
   - **SDK Examples**: Python example using httpx
   - **Free Endpoints**: List the honeypot endpoints
   - **Categories**: Brief description of each category (link to /discover)

Add route:
```python
@app.route("/docs")
def docs_page():
    return render_template_string(DOCS_HTML, nav=NAV_HTML, footer=FOOTER_HTML)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_discover.py::test_docs_page_exists -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app.py tests/test_discover.py
git commit -m "feat: add /docs integration guide page"
```

---

## Workstream F: Final Cleanup (Task 15)

### Task 15: Update sitemap.xml and meta tags

**Files:**
- Modify: `app.py:6819-6857` (sitemap route)
- Modify: `app.py:2065-2086` (meta tags in LANDING_HTML)

**Step 1: Update sitemap to include /docs, remove /blog, /buy-credits**

In the `sitemap()` function, update the static pages list:
- Add: `/docs`
- Remove: `/blog`, `/buy-credits`, `/sdk`, `/catalog`, `/marketplace`, `/agents`, `/changelog`, `/stats`
- Keep: `/`, `/discover`, `/docs`, `/preview`, `/health`

**Step 2: Update meta tags**

In the new LANDING_HTML, ensure:
- og:description does NOT mention "140+ endpoints"
- twitter:description does NOT mention endpoint counts
- Schema.org JSON-LD updated to match

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v --ignore=tests/test_agent_identity.py --ignore=tests/test_v2_integration.py`
Expected: All tests pass

**Step 4: Commit**

```bash
git add app.py
git commit -m "feat: update sitemap and meta tags for platform redesign"
```

---

## Summary

| Task | Workstream | Description |
|------|-----------|-------------|
| 1 | A: Pricing | Move data endpoints to paid tier |
| 2 | A: Pricing | Remove explicit pricing from templates |
| 3 | A: Pricing | Hide service counts from discover stats |
| 4 | B: Protection | Strip schemas/prices from /discover JSON |
| 5 | B: Protection | Strip source attribution from skills search |
| 6 | C: Discovery | Slim down agent.json |
| 7 | C: Discovery | Slim down llms.txt |
| 8 | C: Discovery | Update robots.txt |
| 9 | D: Access | Auth-protect /skills/search |
| 10 | D: Access | (Covered by Task 4) |
| 11 | E: Website | Create shared nav + footer components |
| 12 | E: Website | Refresh homepage |
| 13 | E: Website | Redesign /discover page |
| 14 | E: Website | Add /docs page |
| 15 | F: Cleanup | Update sitemap + meta tags |

**Estimated commits:** 14
**Key test files:** `tests/test_pricing.py`, `tests/test_discover.py`
