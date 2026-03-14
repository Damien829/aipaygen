# Funnel Attribution & Onboarding Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add source attribution and first-call tracking to API keys so we can diagnose the 412-keys-3-calls gap and measure launch post effectiveness.

**Architecture:** Add `source` and `first_used_at` columns to `api_keys` table. Capture `?ref=` params via cookie across the website. Improve key generation response with quickstart guidance. Extend admin funnel dashboard with key attribution stats.

**Tech Stack:** Python/Flask, SQLite, Jinja2 templates

---

## Chunk 1: Database Schema & Core Functions

### Task 1: Add `source` and `first_used_at` columns to api_keys

**Files:**
- Modify: `api_keys.py:17-33` (init_keys_db)
- Modify: `api_keys.py:36-44` (generate_key)
- Modify: `api_keys.py:81-100` (deduct)
- Modify: `api_keys.py:103-126` (deduct_metered)
- Test: `tests/test_api_keys.py`

- [ ] **Step 1: Write failing tests for source and first_used_at**

Add to `tests/test_api_keys.py`:

```python
# ── Attribution ───────────────────────────────────────────────────────────

def test_generate_key_default_source():
    key_data = api_keys.generate_key(initial_balance=0.0)
    with sqlite3.connect(api_keys.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT source FROM api_keys WHERE key = ?", (key_data["key"],)).fetchone()
    assert row["source"] == "unknown"


def test_generate_key_with_source():
    key_data = api_keys.generate_key(initial_balance=0.0, source="hackernews")
    with sqlite3.connect(api_keys.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT source FROM api_keys WHERE key = ?", (key_data["key"],)).fetchone()
    assert row["source"] == "hackernews"


def test_first_used_at_set_on_first_deduct():
    key_data = api_keys.generate_key(initial_balance=10.0)
    # Before any call, first_used_at is None
    with sqlite3.connect(api_keys.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT first_used_at FROM api_keys WHERE key = ?", (key_data["key"],)).fetchone()
    assert row["first_used_at"] is None

    api_keys.deduct(key_data["key"], 1.0)
    with sqlite3.connect(api_keys.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT first_used_at FROM api_keys WHERE key = ?", (key_data["key"],)).fetchone()
    first_time = row["first_used_at"]
    assert first_time is not None

    # Second deduct should NOT change first_used_at
    api_keys.deduct(key_data["key"], 1.0)
    with sqlite3.connect(api_keys.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT first_used_at FROM api_keys WHERE key = ?", (key_data["key"],)).fetchone()
    assert row["first_used_at"] == first_time


def test_first_used_at_set_on_deduct_metered():
    key_data = api_keys.generate_key(initial_balance=10.0)
    api_keys.deduct_metered(key_data["key"], 1000, 500, 0.25, 1.25)
    with sqlite3.connect(api_keys.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT first_used_at FROM api_keys WHERE key = ?", (key_data["key"],)).fetchone()
    assert row["first_used_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_api_keys.py::test_generate_key_default_source tests/test_api_keys.py::test_generate_key_with_source tests/test_api_keys.py::test_first_used_at_set_on_first_deduct tests/test_api_keys.py::test_first_used_at_set_on_deduct_metered -v`
Expected: FAIL — `source` and `first_used_at` columns don't exist

- [ ] **Step 3: Update `init_keys_db()` with migration**

In `api_keys.py`, after the existing `CREATE INDEX` statements (line 33), add:

```python
        # Migrations — idempotent column additions
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN source TEXT DEFAULT 'unknown'")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN first_used_at TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
```

- [ ] **Step 4: Update `generate_key()` to accept `source`**

Change signature and INSERT in `api_keys.py:36-44`:

```python
def generate_key(initial_balance: float = 0.0, label: str = "", source: str = "unknown") -> dict:
    key = "apk_" + secrets.token_urlsafe(32)
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO api_keys (key, label, balance_usd, created_at, source) VALUES (?, ?, ?, ?, ?)",
            (key, label, initial_balance, now, source),
        )
    return {"key": key, "balance_usd": initial_balance, "label": label, "created_at": now, "source": source}
```

- [ ] **Step 5: Update `deduct()` to set `first_used_at` on first call**

Change the UPDATE in `api_keys.py:88-93`:

```python
        cur = c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd - ?, total_spent = total_spent + ?, "
            "call_count = call_count + 1, last_used_at = ?, "
            "first_used_at = CASE WHEN first_used_at IS NULL THEN ? ELSE first_used_at END "
            "WHERE key = ? AND is_active = 1 AND balance_usd >= ?",
            (amount, amount, now, now, key, amount),
        )
```

- [ ] **Step 6: Update `deduct_metered()` to set `first_used_at` on first call**

Change the UPDATE in `api_keys.py:118-122`:

```python
        c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd - ?, total_spent = total_spent + ?, "
            "call_count = call_count + 1, last_used_at = ?, "
            "first_used_at = CASE WHEN first_used_at IS NULL THEN ? ELSE first_used_at END "
            "WHERE key = ?",
            (cost, cost, now, now, key),
        )
```

- [ ] **Step 7: Update `get_key_status()` to include new columns**

Change the SELECT in `api_keys.py:62-64`:

```python
        row = c.execute(
            "SELECT key, label, balance_usd, total_spent, call_count, is_active, created_at, last_used_at, source, first_used_at FROM api_keys WHERE key = ?",
            (key,),
        ).fetchone()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_api_keys.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
cd /home/damien809/agent-service
git add api_keys.py tests/test_api_keys.py
git commit -m "feat: add source attribution and first_used_at tracking to api_keys"
```

---

## Chunk 2: Route Changes — Attribution Capture & Onboarding

### Task 2: Add source to key generation route and quickstart response

**Files:**
- Modify: `routes/auth.py:60-75` (auth_generate_key)
- Modify: `routes/auth.py:308-316` (stripe webhook generate_key call)
- Test: `tests/test_auth_routes.py`

- [ ] **Step 1: Write failing test for source capture and quickstart**

Add to `tests/test_auth_routes.py`:

```python
def test_generate_key_captures_source(client):
    resp = client.post("/auth/generate-key", json={"source": "hackernews"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "quickstart" in data
    assert "curl_example" in data["quickstart"]
    assert data["key"] in data["quickstart"]["curl_example"]


def test_generate_key_default_source(client):
    resp = client.post("/auth/generate-key", json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "quickstart" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_auth_routes.py::test_generate_key_captures_source tests/test_auth_routes.py::test_generate_key_default_source -v`
Expected: FAIL — no `quickstart` in response

- [ ] **Step 3: Update `/auth/generate-key` in `routes/auth.py:60-75`**

```python
@auth_bp.route("/auth/generate-key", methods=["POST"])
def auth_generate_key():
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr)
    if not check_identity_rate_limit(ip):
        return jsonify({"error": "rate_limited", "message": "Too many key generation requests. Max 10/min."}), 429
    data = request.get_json() or {}
    label = data.get("label", "")
    source = data.get("source", request.cookies.get("aipaygen_ref", "api-direct"))
    key_data = generate_key(initial_balance=0.0, label=label, source=source)
    api_key = key_data["key"]
    return jsonify({
        "key": api_key,
        "balance_usd": key_data["balance_usd"],
        "label": key_data["label"],
        "created_at": key_data["created_at"],
        "source": key_data["source"],
        "usage": "Add 'Authorization: Bearer <key>' to your requests. Topup via POST /auth/topup.",
        "_meta": {"free": True},
        "quickstart": {
            "curl_example": f"curl -X POST -H 'Authorization: Bearer {api_key}' {BASE_URL}/sentiment -d '{{\"text\": \"hello world\"}}'",
            "mcp_install": "pip install aipaygen-mcp && claude mcp add aipaygen -- aipaygen-mcp",
            "docs": f"{BASE_URL}/docs",
            "free_calls": 10,
            "note": "You get 10 free calls/day. No payment needed to start.",
        },
    })
```

- [ ] **Step 4: Update Stripe webhook `generate_key` call at `routes/auth.py:314`**

```python
                ref_source = meta.get("ref_source", "stripe")
                new_key = generate_key(initial_balance=amount, label=label, source=ref_source)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_auth_routes.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd /home/damien809/agent-service
git add routes/auth.py tests/test_auth_routes.py
git commit -m "feat: add source attribution + quickstart to key generation"
```

---

### Task 3: Add ref cookie capture on website routes

**Files:**
- Modify: `routes/meta.py:283-291` (landing route)
- Test: `tests/test_auth_routes.py` (or `tests/test_meta_routes.py` if exists)

- [ ] **Step 1: Write failing test for ref cookie**

```python
def test_landing_sets_ref_cookie(client):
    resp = client.get("/?ref=hackernews")
    assert resp.status_code == 200
    cookies = {c.name: c.value for c in client.cookie_jar}
    assert cookies.get("aipaygen_ref") == "hackernews"


def test_landing_no_ref_no_cookie(client):
    resp = client.get("/")
    assert resp.status_code == 200
    cookies = {c.name: c.value for c in client.cookie_jar}
    assert "aipaygen_ref" not in cookies
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_meta_routes.py::test_landing_sets_ref_cookie -v` (or whichever test file has meta route tests)
Expected: FAIL — no cookie set

- [ ] **Step 3: Update landing route in `routes/meta.py:283-291`**

```python
@meta_bp.route("/")
def landing():
    try:
        resp = make_response(render_template("index.html"))
    except Exception:
        resp = make_response(render_template("landing.html", nav=NAV_HTML, footer=FOOTER_HTML))
    resp.headers["Link"] = '</llms.txt>; rel="llms-txt"'
    ref = request.args.get("ref", "")
    if ref:
        resp.set_cookie("aipaygen_ref", ref, max_age=30*86400, secure=True, httponly=True, samesite="Lax")
    return resp
```

- [ ] **Step 4: Also set ref cookie on `/try` and `/buy-credits` routes**

Find the `/try` route in `routes/meta.py` and `/buy-credits` route in `routes/auth.py`. Add the same cookie logic:

```python
    ref = request.args.get("ref", "")
    if ref:
        resp.set_cookie("aipaygen_ref", ref, max_age=30*86400, secure=True, httponly=True, samesite="Lax")
```

For `/buy-credits`, also pass `ref_source` into Stripe checkout metadata (alongside existing `ref_agent`). In the `/stripe/create-checkout` route, add to metadata:

```python
        ref_source = request.cookies.get("aipaygen_ref", "stripe")
        # Add to metadata dict:
        "ref_source": ref_source,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/damien809/agent-service && python -m pytest tests/ -k "ref_cookie or landing" -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd /home/damien809/agent-service
git add routes/meta.py routes/auth.py tests/
git commit -m "feat: capture ref attribution via cookie across website routes"
```

---

## Chunk 3: Admin Dashboard — Key Attribution Stats

### Task 4: Fix duplicate `/admin/funnel` route and add attribution stats

**Files:**
- Modify: `routes/admin.py:875-882` (rename duplicate route)
- Modify: `routes/admin.py:169-218` (extend HTML dashboard)

- [ ] **Step 1: Rename duplicate JSON route at `routes/admin.py:875`**

Change from:
```python
@admin_bp.route("/admin/funnel")
@require_admin
def admin_funnel():
```
To:
```python
@admin_bp.route("/admin/funnel-data")
@require_admin
def admin_funnel_data():
```

- [ ] **Step 2: Add key attribution stats to the HTML funnel dashboard**

In the `funnel_dashboard()` function (around line 189, after `stats = get_funnel_stats(days)`), add a query for key stats:

```python
    # Key attribution stats
    import api_keys as _ak
    key_stats_html = ""
    try:
        with sqlite3.connect(_ak.DB_PATH) as kc:
            kc.row_factory = sqlite3.Row
            rows = kc.execute("""
                SELECT source,
                       COUNT(*) as total,
                       SUM(CASE WHEN call_count = 0 THEN 1 ELSE 0 END) as zero_calls,
                       SUM(CASE WHEN call_count > 0 THEN 1 ELSE 0 END) as active
                FROM api_keys WHERE is_active = 1
                GROUP BY source ORDER BY total DESC
            """).fetchall()
            for r in rows:
                pct = round(100 * r["active"] / r["total"], 1) if r["total"] else 0
                key_stats_html += (
                    f'<tr><td>{r["source"]}</td><td>{r["total"]}</td>'
                    f'<td>{r["zero_calls"]}</td><td>{r["active"]}</td><td>{pct}%</td></tr>'
                )
            # Median time to first call
            median_row = kc.execute("""
                SELECT first_used_at, created_at FROM api_keys
                WHERE first_used_at IS NOT NULL ORDER BY
                (julianday(first_used_at) - julianday(created_at))
                LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM api_keys WHERE first_used_at IS NOT NULL)
            """).fetchone()
            if median_row:
                from datetime import datetime as _dt
                created = _dt.fromisoformat(median_row["created_at"])
                first = _dt.fromisoformat(median_row["first_used_at"])
                median_mins = round((first - created).total_seconds() / 60, 1)
                median_label = f"{median_mins} min" if median_mins < 60 else f"{round(median_mins/60, 1)} hr"
            else:
                median_label = "N/A"
    except Exception:
        key_stats_html = '<tr><td colspan="5">Error loading key stats</td></tr>'
        median_label = "N/A"
```

Then add the HTML section to the dashboard response (insert before the closing `</div></body>` of the existing template). The exact insertion point is in the HTML string that `funnel_dashboard()` returns — add a new card:

```html
<div class="card" style="margin-top:24px">
  <h2>Key Attribution</h2>
  <p style="color:#888;margin-bottom:12px">Median time to first call: <b style="color:#6366f1">{median_label}</b></p>
  <table style="width:100%;border-collapse:collapse">
    <tr style="color:#888;text-align:left"><th>Source</th><th>Keys</th><th>0 Calls</th><th>Active</th><th>Activation %</th></tr>
    {key_stats_html}
  </table>
</div>
```

- [ ] **Step 3: Run the full test suite to check for regressions**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_admin_routes.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /home/damien809/agent-service
git add routes/admin.py
git commit -m "feat: add key attribution stats to admin funnel dashboard"
```

---

### Task 5: Update launch post links with ref params

**Files:**
- Modify: `SHOW_HN.md`
- Modify: `REDDIT_LAUNCH.md`

- [ ] **Step 1: Add `?ref=` params to all aipaygen.com links**

In `SHOW_HN.md`, change all `https://aipaygen.com` links to include `?ref=hackernews`:
- `https://aipaygen.com` → `https://aipaygen.com?ref=hackernews`
- `https://mcp.aipaygen.com/mcp` stays as-is (MCP endpoint, not website)

In `REDDIT_LAUNCH.md`, use `?ref=reddit`:
- `https://aipaygen.com` → `https://aipaygen.com?ref=reddit`

- [ ] **Step 2: Commit**

```bash
cd /home/damien809/agent-service
git add SHOW_HN.md REDDIT_LAUNCH.md
git commit -m "feat: add ref attribution params to launch post links"
```

---

### Task 6: Run full test suite

- [ ] **Step 1: Run all 1382 tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: ALL PASS (1382+ tests, 0 failures)

- [ ] **Step 2: Manual smoke test**

Run:
```bash
curl -s -X POST http://localhost:5001/auth/generate-key -H 'Content-Type: application/json' -d '{"source":"test"}' | python3 -m json.tool
```
Expected: Response includes `source: "test"` and `quickstart` object with curl example

---
