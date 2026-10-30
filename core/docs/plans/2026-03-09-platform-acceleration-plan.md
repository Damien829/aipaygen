# Platform Acceleration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Maximize revenue capture, discovery, platform moat, and retention before x402 adoption wave.

**Architecture:** Four waves of features building on each other. Wave 1 (Resend + accounts + dashboard) unlocks Waves 2-4. All persistence in SQLite (consistent with existing arch). Email via Resend free tier. Magic link auth via signed JWTs.

**Tech Stack:** resend (email), PyJWT (already installed), SQLite (existing), Stripe (existing)

---

## Environment Setup Required

Before starting implementation:

1. Sign up for Resend at resend.com (free tier)
2. Get API key and add to `.env`: `RESEND_API_KEY=re_xxxx`
3. Verify domain `aipaygen.com` in Resend dashboard (DNS TXT record)

---

## Wave 1: Revenue Capture

### Task 1: Resend Email Service

**Files:**
- Create: `email_service.py`
- Modify: `requirements.txt`
- Test: `tests/test_email.py`

**Step 1: Add resend to requirements**

Add `resend==2.5.0` to `requirements.txt`. Install with `pip install resend==2.5.0`.

**Step 2: Write the failing test**

```python
# tests/test_email.py
import pytest
from unittest.mock import patch, MagicMock

def test_send_api_key_email():
    from email_service import send_api_key_email
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-123"}
        result = send_api_key_email("user@example.com", "apk_test123", 5.0)
        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["user@example.com"]
        assert "apk_test123" in call_args["html"]

def test_send_api_key_email_no_key():
    from email_service import send_api_key_email
    result = send_api_key_email("user@example.com", "", 5.0)
    assert result is False

def test_send_nudge_email():
    from email_service import send_free_tier_nudge
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-456"}
        result = send_free_tier_nudge("user@example.com", tools_used=4, calls_made=10)
        assert result is True
        assert "10" in mock_send.call_args[0][0]["html"]

def test_send_magic_link():
    from email_service import send_magic_link
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-789"}
        result = send_magic_link("user@example.com", "https://aipaygen.com/auth/verify?token=abc")
        assert result is True
        assert "verify" in mock_send.call_args[0][0]["html"]

def test_send_weekly_digest():
    from email_service import send_weekly_digest
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-weekly"}
        result = send_weekly_digest("user@example.com", calls=42, top_tools=["research", "summarize"], spent=1.25)
        assert result is True
        assert "42" in mock_send.call_args[0][0]["html"]
```

Run: `pytest tests/test_email.py -v`
Expected: FAIL (email_service not found)

**Step 3: Implement email_service.py**

Four email functions: `send_api_key_email`, `send_free_tier_nudge`, `send_magic_link`, `send_weekly_digest`. All use resend SDK, return True/False. HTML emails with AiPayGen branding (dark theme matching site). Use server-side rendered HTML only (no client-side DOM manipulation).

**Step 4: Run tests**

Run: `pytest tests/test_email.py -v`
Expected: 5 PASS

**Step 5: Commit**

```bash
git add email_service.py tests/test_email.py requirements.txt
git commit -m "feat: add Resend email service (key delivery, nudges, magic links, digests)"
```

---

### Task 2: Accounts Database and Magic Link Auth

**Files:**
- Create: `accounts.py`
- Create: `routes/accounts.py`
- Modify: `app.py` (register blueprint, init DB)
- Test: `tests/test_accounts.py`

**Step 1: Write the failing test**

```python
# tests/test_accounts.py
import pytest, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from accounts import init_accounts_db, create_or_get_account, get_account_by_email, link_key_to_account, get_account_keys

def setup_module():
    os.environ["ACCOUNTS_DB"] = ":memory:"
    init_accounts_db()

def test_create_account():
    acct = create_or_get_account("test@example.com")
    assert acct["email"] == "test@example.com"
    assert acct["id"] is not None

def test_get_existing_account():
    a1 = create_or_get_account("same@example.com")
    a2 = create_or_get_account("same@example.com")
    assert a1["id"] == a2["id"]

def test_get_account_by_email():
    create_or_get_account("lookup@example.com")
    acct = get_account_by_email("lookup@example.com")
    assert acct is not None

def test_get_account_not_found():
    assert get_account_by_email("nope@example.com") is None

def test_link_key_to_account():
    acct = create_or_get_account("keys@example.com")
    link_key_to_account(acct["id"], "apk_testkey123")
    keys = get_account_keys(acct["id"])
    assert len(keys) == 1
    assert keys[0]["api_key"] == "apk_testkey123"

def test_link_duplicate_key():
    acct = create_or_get_account("dup@example.com")
    link_key_to_account(acct["id"], "apk_dupkey")
    link_key_to_account(acct["id"], "apk_dupkey")
    keys = get_account_keys(acct["id"])
    assert len(keys) == 1
```

Run: `pytest tests/test_accounts.py -v`
Expected: FAIL (accounts not found)

**Step 2: Implement accounts.py**

SQLite tables:
- `accounts (id, email UNIQUE, created_at, last_login, digest_opt_out)`
- `account_keys (id, account_id FK, api_key UNIQUE, linked_at)`

Functions: `create_or_get_account`, `get_account_by_email`, `link_key_to_account`, `get_account_keys`, `update_last_login`, `set_digest_opt_out`. WAL mode. Auto-init on import.

**Step 3: Run tests**

Run: `pytest tests/test_accounts.py -v`
Expected: 6 PASS

**Step 4: Implement routes/accounts.py**

Blueprint with routes:
- `POST /auth/magic-link` — sends magic link via Resend
- `GET /auth/verify` — verifies token, sets JWT cookie (24h), redirects to /dashboard
- `GET /auth/login` — login form page (server-rendered HTML)
- `GET /my-key` — key recovery page (server-rendered HTML)
- `POST /auth/key-lookup` — lookup by email (requires auth or sends magic link; prevents email enumeration)
- `GET /dashboard` — usage dashboard (balance, calls, keys) requires auth
- `GET /unsubscribe` — opt out of digests

Security notes:
- JWT secret from `JWT_SECRET` or `ADMIN_SECRET` env var
- Magic link tokens expire in 15 minutes
- Session cookies: httponly, secure, samesite=Lax
- Key lookup always returns same message (prevent enumeration)
- All HTML is server-rendered (no client-side DOM injection of user data)

**Step 5: Register blueprint in app.py**

Add import and `app.register_blueprint(accounts_bp)`. Add `init_accounts_db()` near other DB inits.

**Step 6: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS (134 + 6 + 5 = 145)

**Step 7: Commit**

```bash
git add accounts.py routes/accounts.py tests/test_accounts.py app.py
git commit -m "feat: magic link accounts, dashboard, key recovery"
```

---

### Task 3: Wire Email Into Stripe Webhook + Fix Race Condition

**Files:**
- Modify: `routes/auth.py:584-650` (webhook handler + success page)
- Test: `tests/test_stripe_email.py`

**Step 1: Modify webhook handler (routes/auth.py ~line 584-626)**

After key generation in `checkout.session.completed` handler, add:
- Import `send_api_key_email` from `email_service`
- Import `create_or_get_account`, `link_key_to_account` from `accounts`
- Get `customer_email` from `session.customer_details.email`
- If email and key exist: send email, create account, link key

**Step 2: Add key-status polling endpoint**

```python
@auth_bp.route("/auth/key-status", methods=["GET"])
def key_status():
    session_id = request.args.get("session_id", "")
    if not session_id:
        return jsonify({"ready": False})
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        key = session.metadata.get("api_key")
        if key:
            return jsonify({"ready": True, "api_key": key, "balance": session.metadata.get("balance_usd", "0")})
        return jsonify({"ready": False})
    except Exception:
        return jsonify({"ready": False})
```

**Step 3: Update success page to poll**

Replace direct metadata read with JS that polls `/auth/key-status?session_id=xxx` every 2s until `ready: true`. Use `textContent` for displaying key (not innerHTML).

**Step 4: Run tests, commit**

```bash
git add routes/auth.py tests/test_stripe_email.py
git commit -m "feat: email API key on purchase, fix webhook race condition"
```

---

## Wave 2: Discovery and SEO

### Task 4: OpenAPI Spec Auto-Generation

**Files:**
- Create: `openapi_gen.py`
- Modify: `routes/meta.py` (add /openapi.json route)
- Test: `tests/test_openapi.py`

**Step 1: Write the failing test**

```python
# tests/test_openapi.py
def test_openapi_spec_structure():
    from openapi_gen import generate_openapi_spec
    spec = generate_openapi_spec()
    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "AiPayGen API"
    assert "/research" in spec["paths"]
    assert "securitySchemes" in spec["components"]

def test_openapi_has_all_routes():
    from openapi_gen import generate_openapi_spec
    spec = generate_openapi_spec()
    assert len(spec["paths"]) >= 30
```

**Step 2: Implement openapi_gen.py**

`generate_openapi_spec()` function that:
- Imports `routes` dict from app module scope (or accepts as param)
- Maps each `RouteConfig` to OpenAPI path object
- Includes description, pricing in x-extension, auth methods
- Adds free endpoints manually
- Returns full OpenAPI 3.1.0 dict

**Step 3: Add route in routes/meta.py**

```python
@meta_bp.route("/openapi.json")
def openapi_spec():
    from openapi_gen import generate_openapi_spec
    return jsonify(generate_openapi_spec())
```

**Step 4: Run tests, commit**

```bash
git add openapi_gen.py routes/meta.py tests/test_openapi.py
git commit -m "feat: auto-generated OpenAPI 3.1.0 spec from routes dict"
```

---

### Task 5: AI Plugin Manifest + Enhanced llms.txt + 402 Link Headers

**Files:**
- Modify: `routes/meta.py` (add ai-plugin.json, enhance llms.txt)
- Modify: `app.py` (add Link headers to 402)

**Step 1: Add /.well-known/ai-plugin.json in routes/meta.py**

Return OpenAI plugin manifest format: schema_version, name, descriptions, auth config, API URL pointing to /openapi.json.

**Step 2: Enhance /llms.txt handler**

Expand to include: per-tool descriptions with input/output schema, pricing tiers, curl examples for top 10 tools, auth methods.

**Step 3: Add Link headers to 402 responses in app.py**

In the 402 enrichment section (~line 791), append to captured headers:
- `Link: </openapi.json>; rel="service-desc"`
- `Link: </.well-known/ai-plugin.json>; rel="ai-plugin"`

**Step 4: Update robots.txt to allow key discovery pages**

Ensure `/openapi.json`, `/.well-known/ai-plugin.json`, `/llms.txt` are allowed.

**Step 5: Run tests, commit**

```bash
git add routes/meta.py app.py
git commit -m "feat: ai-plugin.json, enhanced llms.txt, 402 discovery headers"
```

---

## Wave 3: Platform Moat

### Task 6: Multi-Step Workflow Engine

**Files:**
- Create: `workflow_engine.py`
- Create: `routes/workflow.py`
- Modify: `app.py` (register blueprint + x402 route)
- Test: `tests/test_workflow.py`

**Step 1: Write the failing test**

```python
# tests/test_workflow.py
from workflow_engine import validate_workflow

def test_validate_valid_workflow():
    steps = [{"tool": "research", "input": {"topic": "AI agents"}}, {"tool": "summarize"}]
    assert validate_workflow(steps) == []

def test_validate_empty():
    assert len(validate_workflow([])) > 0

def test_validate_unknown_tool():
    errors = validate_workflow([{"tool": "nonexistent"}])
    assert any("unknown" in e.lower() for e in errors)

def test_validate_too_many_steps():
    steps = [{"tool": "research", "input": {"topic": "x"}}] * 11
    assert any("10" in e for e in validate_workflow(steps))
```

**Step 2: Implement workflow_engine.py**

- `validate_workflow(steps)` — check tool names, max 10 steps, return error list
- `execute_workflow(steps, ip, api_key)` — run sequentially, pipe output to next input, apply 15% discount, return results with per-step timing
- Known tools list derived from route names

**Step 3: Add routes/workflow.py**

- `POST /workflow/run` — accepts `{"steps": [...]}`, validates, executes, returns all results

**Step 4: Register in app.py, add x402 route**

```python
"POST /workflow/run": RouteConfig(...)  # priced at $0.01 base + per-step
```

**Step 5: Run tests, commit**

```bash
git add workflow_engine.py routes/workflow.py tests/test_workflow.py app.py
git commit -m "feat: multi-step workflow engine with 15% chain discount"
```

---

### Task 7: Persistent Agent Sessions

**Files:**
- Create: `sessions.py`
- Create: `routes/sessions.py`
- Modify: `app.py`
- Test: `tests/test_sessions.py`

**Step 1: Write the failing test**

```python
# tests/test_sessions.py
import os
os.environ.setdefault("SESSIONS_DB", ":memory:")
from sessions import init_sessions_db, create_session, get_session, update_session_context

def setup_module():
    init_sessions_db()

def test_create_session():
    sid = create_session(agent_id="agent-1", context={"topic": "AI"})
    assert sid is not None

def test_get_session():
    sid = create_session(agent_id="agent-2", context={"topic": "ML"})
    s = get_session(sid)
    assert s["agent_id"] == "agent-2"
    assert s["context"]["topic"] == "ML"

def test_update_context():
    sid = create_session(agent_id="agent-3", context={"history": []})
    update_session_context(sid, {"history": [{"role": "user", "content": "hello"}]})
    s = get_session(sid)
    assert len(s["context"]["history"]) == 1

def test_session_not_found():
    assert get_session("nonexistent-id") is None
```

**Step 2: Implement sessions.py**

SQLite table: `sessions (id TEXT PK, agent_id, context JSON, created_at, last_active, ttl_hours DEFAULT 24)`.
Functions: `create_session`, `get_session`, `update_session_context`, `cleanup_expired`.

**Step 3: Add routes/sessions.py**

- `POST /session/start` — create session, return session_id
- `POST /session/call` — execute tool within session context
- `GET /session/<id>` — get session state

**Step 4: Register in app.py, add x402 routes**

**Step 5: Run tests, commit**

```bash
git add sessions.py routes/sessions.py tests/test_sessions.py app.py
git commit -m "feat: persistent agent sessions with 24h TTL"
```

---

### Task 8: Webhook Registration for Key Holders

**Files:**
- Create: `webhook_dispatch.py`
- Modify: `routes/auth.py`
- Test: `tests/test_webhook_dispatch.py`

**Step 1: Write the failing test**

Test register, list, trigger dispatch (mock HTTP), retry on failure.

**Step 2: Implement webhook_dispatch.py**

SQLite table: `user_webhooks (id, api_key, url, events JSON, created_at)`.
`dispatch_event(event, api_key, payload)` — POST to registered URLs, 3 retries with exponential backoff.

**Step 3: Add routes to auth.py**

- `POST /webhooks/register` — requires Bearer apk_xxx
- `GET /webhooks` — list for current key
- `DELETE /webhooks/<id>` — remove

**Step 4: Wire into key events**

Call dispatch on: `balance_low` (balance < $0.50), `free_tier_exhausted`.

**Step 5: Run tests, commit**

```bash
git add webhook_dispatch.py routes/auth.py tests/test_webhook_dispatch.py
git commit -m "feat: webhook registration and event dispatch"
```

---

## Wave 4: Retention

### Task 9: Expanded /try Page

**Files:**
- Modify: `routes/meta.py:3647-3696`

**Step 1: Expand tool list from 6 to 15**

Add: research, scrape_website, code, compare, extract, vision, analyze, questions, decide.

**Step 2: Add copy-as-curl button**

Each result includes a pre-built curl command. Use `textContent` for safe DOM updates.

**Step 3: Increase rate limit to 10/10min**

**Step 4: Run tests, commit**

```bash
git add routes/meta.py
git commit -m "feat: expanded /try page with 15 tools and copy-as-curl"
```

---

### Task 10: Upgrade Hint Headers + Personalized 402

**Files:**
- Modify: `app.py` (WSGI wrapper + 402 enrichment)

**Step 1: Add X-Upgrade-Hint header**

In free tier section of `_api_key_wsgi`, when `remaining <= 3`:
```python
headers.append(("X-Upgrade-Hint", "true"))
```

**Step 2: Personalize 402 with usage stats**

When free tier exhausted, query today's usage from `free_tier_usage` table. Include in 402 body:
```json
{"free_tier": {"status": "exhausted", "calls_today": 10, "tools_used": 3, "message": "..."}}
```

**Step 3: Run tests, commit**

```bash
git add app.py
git commit -m "feat: upgrade hints and personalized 402 responses"
```

---

## Execution Order Summary

| Task | Description | Depends On | Parallelizable |
|------|-------------|-----------|----------------|
| 1 | Resend email service | None | Yes |
| 2 | Accounts + magic link + dashboard | Task 1 | No |
| 3 | Stripe email + race fix | Tasks 1, 2 | No |
| 4 | OpenAPI spec auto-gen | None | Yes |
| 5 | ai-plugin.json + llms.txt + headers | Task 4 | No |
| 6 | Workflow engine | None | Yes |
| 7 | Persistent sessions | None | Yes |
| 8 | Webhook dispatch | Task 2 | No |
| 9 | Expanded /try page | None | Yes |
| 10 | Upgrade hints + personalized 402 | None | Yes |

**Parallel groups:**
- Group A (independent): Tasks 1, 4, 6, 7, 9, 10
- Group B (sequential): Task 1 -> 2 -> 3
- Group C (sequential): Task 4 -> 5
- Group D (sequential): Task 2 -> 8
