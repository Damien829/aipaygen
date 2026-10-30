# Security Hardening + TF-IDF Wave 4 + Discover UX — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden IP resolution, upgrade ReAct agent to TF-IDF search, and make `/discover` render a clean HTML page for browsers while keeping JSON for agents.

**Architecture:** Three independent workstreams touching `app.py` and `react_agent.py`. Security fixes are isolated helper functions + find-replace. TF-IDF upgrade passes the existing engine instance. Discover uses content negotiation via Accept header.

**Tech Stack:** Flask, Python stdlib, existing `SkillsSearchEngine` class, inline HTML/CSS (no templates)

---

### Task 1: Add `_get_client_ip()` helper to app.py

**Files:**
- Modify: `app.py` — add helper after line 178 (after `require_admin` decorator)
- Test: `tests/test_web.py` (add test)

**Step 1: Write the failing test**

Add to `tests/test_web.py`:

```python
def test_get_client_ip_prefers_cf_header(client):
    """_get_client_ip should prefer CF-Connecting-IP over X-Forwarded-For."""
    with app.test_request_context(headers={
        "CF-Connecting-IP": "1.2.3.4",
        "X-Forwarded-For": "5.6.7.8",
    }):
        from app import _get_client_ip
        assert _get_client_ip() == "1.2.3.4"

def test_get_client_ip_falls_back_to_remote_addr(client):
    """Without CF header, should use REMOTE_ADDR."""
    with app.test_request_context():
        from app import _get_client_ip
        ip = _get_client_ip()
        assert isinstance(ip, str)
```

**Step 2: Run test to verify it fails**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_web.py::test_get_client_ip_prefers_cf_header -v`
Expected: FAIL — `_get_client_ip` not defined

**Step 3: Write the helper**

Add to `app.py` after line 178 (after `require_admin`):

```python
def _get_client_ip():
    """Get client IP — trust CF-Connecting-IP (Cloudflare), fall back to REMOTE_ADDR.
    Never trust X-Forwarded-For directly as it's spoofable."""
    return request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown").split(",")[0].strip()
```

**Step 4: Run test to verify it passes**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_web.py::test_get_client_ip_prefers_cf_header tests/test_web.py::test_get_client_ip_falls_back_to_remote_addr -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /home/damien809/agent-service
git add app.py tests/test_web.py
git commit -m "feat: add _get_client_ip() helper trusting CF-Connecting-IP"
```

---

### Task 2: Replace all X-Forwarded-For usages with `_get_client_ip()`

**Files:**
- Modify: `app.py` — 7 locations

**Step 1: Replace all occurrences**

Find and replace these exact patterns in `app.py`:

| Line | Old | New |
|------|-----|-----|
| 912 | `ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()` | `ip = _get_client_ip()` |
| 3140 | `ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()` | `ip = _get_client_ip()` |
| 3238 | `ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()` | `ip = _get_client_ip()` |
| 3410 | `ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()` | `ip = _get_client_ip()` |
| 6097 | `_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()` | `_ip = _get_client_ip()` |
| 6111 | `_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()` | `_ip = _get_client_ip()` |
| 6492 | `ip = request.headers.get("X-Forwarded-For", request.remote_addr)` | `ip = _get_client_ip()` |

Also fix line 6493-6494 — the `if ip and "," in ip:` block after 6492 is no longer needed since `_get_client_ip()` already handles comma splitting. Remove it.

**Step 2: Run existing tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/ -v --ignore=tests/test_agent_identity.py --ignore=tests/test_v2_integration.py -x`
Expected: All tests PASS

**Step 3: Commit**

```bash
cd /home/damien809/agent-service
git add app.py
git commit -m "security: replace X-Forwarded-For with _get_client_ip() across 7 locations"
```

---

### Task 3: Add query string length limit

**Files:**
- Modify: `app.py` — add a `@app.before_request` hook

**Step 1: Write the failing test**

Add to `tests/test_web.py`:

```python
def test_rejects_oversized_query_params(client):
    huge = "a" * 10001
    resp = client.get(f"/free/time?q={huge}")
    assert resp.status_code == 400
    assert b"too long" in resp.data.lower() or b"too_long" in resp.data.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_web.py::test_rejects_oversized_query_params -v`
Expected: FAIL — currently returns 200

**Step 3: Add before_request hook**

Add after the existing `track_referral` before_request handler (after line ~919):

```python
@app.before_request
def check_query_param_lengths():
    for key, value in request.args.items():
        if len(value) > 10000:
            return jsonify({"error": "param_too_long", "message": f"Query parameter '{key}' exceeds 10,000 character limit"}), 400
```

**Step 4: Run test to verify it passes**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_web.py::test_rejects_oversized_query_params -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /home/damien809/agent-service
git add app.py tests/test_web.py
git commit -m "security: reject query params exceeding 10K chars"
```

---

### Task 4: Upgrade ReAct agent `search_skills` to use TF-IDF

**Files:**
- Modify: `react_agent.py:328-358` — update `make_tool_handler` signature and search_skills handler
- Modify: `app.py:6892-6898,6931-6937` — pass `_skills_engine` to both agent endpoints
- Test: `tests/test_react_agent.py`

**Step 1: Write the failing test**

Add to `tests/test_react_agent.py`:

```python
def test_make_tool_handler_accepts_search_engine():
    """make_tool_handler should accept optional skills_search_engine param."""
    from react_agent import make_tool_handler
    mock_engine = type("MockEngine", (), {"search": lambda self, q, top_n=10: [{"name": "test_skill", "description": "A test", "category": "test", "score": 0.95}]})()
    handler = make_tool_handler({}, memory_search_fn=None, memory_set_fn=None, skills_db_path=":memory:", agent_id="", skills_search_engine=mock_engine)
    result = handler("search_skills", {"query": "test"})
    assert result["count"] == 1
    assert result["skills"][0]["name"] == "test_skill"
    assert "score" in result["skills"][0]
```

**Step 2: Run test to verify it fails**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py::test_make_tool_handler_accepts_search_engine -v`
Expected: FAIL — `make_tool_handler() got an unexpected keyword argument 'skills_search_engine'`

**Step 3: Update `make_tool_handler` in react_agent.py**

Change the function signature at line 328 from:

```python
def make_tool_handler(batch_handlers: dict, memory_search_fn, memory_set_fn,
                      skills_db_path: str, agent_id: str = ""):
```

to:

```python
def make_tool_handler(batch_handlers: dict, memory_search_fn, memory_set_fn,
                      skills_db_path: str, agent_id: str = "", skills_search_engine=None):
```

Replace the `search_skills` handler block (lines 346-358) from:

```python
        if tool_name == "search_skills":
            query = params.get("query", "")
            try:
                conn = sqlite3.connect(skills_db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT name, description, category FROM skills WHERE name LIKE ? OR description LIKE ? LIMIT 10",
                    (f"%{query}%", f"%{query}%"),
                ).fetchall()
                conn.close()
                return {"skills": [dict(r) for r in rows], "count": len(rows)}
            except Exception as e:
                return {"error": str(e)}
```

to:

```python
        if tool_name == "search_skills":
            query = params.get("query", "")
            if skills_search_engine:
                results = skills_search_engine.search(query, top_n=10)
                return {"skills": [{"name": s["name"], "description": s["description"], "category": s["category"], "score": s.get("score", 0)} for s in results], "count": len(results)}
            try:
                conn = sqlite3.connect(skills_db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT name, description, category FROM skills WHERE name LIKE ? OR description LIKE ? LIMIT 10",
                    (f"%{query}%", f"%{query}%"),
                ).fetchall()
                conn.close()
                return {"skills": [dict(r) for r in rows], "count": len(rows)}
            except Exception as e:
                return {"error": str(e)}
```

**Step 4: Update app.py agent endpoints to pass `_skills_engine`**

In `app.py` at line 6892, add `skills_search_engine=_skills_engine`:

```python
    tool_handler = make_tool_handler(
        batch_handlers=BATCH_HANDLERS,
        memory_search_fn=memory_search if agent_id else None,
        memory_set_fn=memory_set if agent_id else None,
        skills_db_path=_skills_db_path,
        agent_id=agent_id,
        skills_search_engine=_skills_engine,
    )
```

Same at line 6931 for the streaming endpoint:

```python
    tool_handler = make_tool_handler(
        batch_handlers=BATCH_HANDLERS,
        memory_search_fn=memory_search if agent_id else None,
        memory_set_fn=memory_set if agent_id else None,
        skills_db_path=_skills_db_path,
        agent_id=agent_id,
        skills_search_engine=_skills_engine,
    )
```

**Step 5: Run tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py -v`
Expected: All PASS (including existing tests — they don't pass `skills_search_engine` so SQL LIKE fallback is used)

**Step 6: Commit**

```bash
cd /home/damien809/agent-service
git add react_agent.py app.py tests/test_react_agent.py
git commit -m "feat: upgrade ReAct search_skills to TF-IDF engine with SQL LIKE fallback"
```

---

### Task 5: Redesign `/discover` with content negotiation

**Files:**
- Modify: `app.py:3887-4100+` — replace the `/discover` route

**Step 1: Write the failing test**

Add to `tests/test_web.py`:

```python
def test_discover_returns_json_for_agents(client):
    resp = client.get("/discover", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "meta" in data
    assert "payment" in data
    assert "categories" in data

def test_discover_returns_html_for_browsers(client):
    resp = client.get("/discover", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" in resp.data or b"<html" in resp.data
    assert b"AiPayGen" in resp.data
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_web.py::test_discover_returns_json_for_agents tests/test_web.py::test_discover_returns_html_for_browsers -v`
Expected: FAIL — current `/discover` doesn't return `meta`/`categories` keys, doesn't return HTML

**Step 3: Rewrite the `/discover` route**

Replace the entire `/discover` function (from `@app.route("/discover")` through the end of its services list and return statement) with the new content-negotiated version. The new function should:

1. Build a `SERVICES` dict organized by category (keys: "AI Processing", "Web Intelligence", "Data & Free", "Agent Platform", "Scraping & Data Collection", etc.)
2. Check `request.accept_mimetypes.best_match(["text/html", "application/json"])`
3. If `text/html`: return `render_template_string(HTML_TEMPLATE, ...)` with a clean, modern HTML page showing categorized services with cards
4. If JSON: return `jsonify({"meta": {...}, "payment": {...}, "categories": {...}, "links": {...}})`

The HTML template should include:
- Professional dark-themed CSS (inline `<style>`)
- Header with AiPayGen name + tagline
- Service cards grouped by category, each showing: endpoint, method badge, price, description
- "Try Free Preview" button linking to `/preview`
- Footer with links to `/llms.txt`, `/openapi.json`, `/agents`
- No wallet address visible on the page (it's in the JSON response under `payment` for agents that need it)

**Step 4: Run tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_web.py -v -x`
Expected: All PASS

**Step 5: Commit**

```bash
cd /home/damien809/agent-service
git add app.py tests/test_web.py
git commit -m "feat: content-negotiated /discover — HTML for browsers, structured JSON for agents"
```

---

### Task 6: Integration test & restart

**Step 1: Run full test suite**

Run: `cd /home/damien809/agent-service && python -m pytest tests/ -v --ignore=tests/test_agent_identity.py --ignore=tests/test_v2_integration.py`
Expected: All PASS

**Step 2: Restart service**

User runs: `sudo systemctl restart aipaygen.service`

**Step 3: Verify endpoints live**

```bash
# Test /discover HTML (browser)
curl -s http://localhost:5001/discover -H "Accept: text/html" | head -20

# Test /discover JSON (agent)
curl -s http://localhost:5001/discover -H "Accept: application/json" | python3 -m json.tool | head -20

# Test /agent with TF-IDF search
curl -s -X POST http://localhost:5001/agent -H "Content-Type: application/json" -d '{"task":"Search for skills related to web scraping","max_steps":3}' | python3 -m json.tool | head -30

# Test query param length limit
curl -s "http://localhost:5001/free/time?q=$(python3 -c 'print("a"*10001)')" | head -5
```

**Step 4: Commit any final fixes**

```bash
cd /home/damien809/agent-service
git add -A
git commit -m "chore: integration test fixes"
```
