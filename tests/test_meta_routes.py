"""Comprehensive tests for routes/meta.py — all 25 endpoints."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── / (landing page) ──────────────────────────────────────────────────────────

def test_landing_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200

def test_landing_has_link_header(client):
    r = client.get("/")
    assert "llms-txt" in (r.headers.get("Link", "") or "")


# ── /health ───────────────────────────────────────────────────────────────────

def test_health_returns_json(client):
    # Clear health cache so it actually runs
    from routes.meta import _health_cache
    _health_cache["data"] = None
    _health_cache["ts"] = 0

    r = client.get("/health")
    assert r.status_code in (200, 503)
    data = r.get_json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded")
    assert "wallet" in data
    assert "checks" in data

def test_health_cached_response(client):
    """Second call within 60s should return cached data."""
    from routes.meta import _health_cache
    _health_cache["data"] = {"status": "healthy", "wallet": "0xtest", "checks": {}}
    _health_cache["ts"] = time.time()

    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "healthy"

def test_health_cached_degraded_returns_503(client):
    from routes.meta import _health_cache
    _health_cache["data"] = {"status": "degraded", "wallet": "0xtest", "checks": {}}
    _health_cache["ts"] = time.time()

    r = client.get("/health")
    assert r.status_code == 503

    # Cleanup
    _health_cache["data"] = None
    _health_cache["ts"] = 0


# ── /api/stats ────────────────────────────────────────────────────────────────

def test_api_stats_returns_json(client):
    from routes.meta import _stats_cache
    _stats_cache["data"] = None
    _stats_cache["ts"] = 0

    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.get_json()
    assert "mcp_tools" in data
    assert isinstance(data["mcp_tools"], int)

def test_api_stats_cached(client):
    from routes.meta import _stats_cache
    _stats_cache["data"] = {"mcp_tools": 999, "skills": 0, "apis": 0}
    _stats_cache["ts"] = time.time()

    r = client.get("/api/stats")
    data = r.get_json()
    assert data["mcp_tools"] == 999

    _stats_cache["data"] = None
    _stats_cache["ts"] = 0


# ── /preview ──────────────────────────────────────────────────────────────────

@patch("routes.meta._cache_get", return_value=None)
@patch("routes.meta._cache_set")
@patch("routes.meta._call_llm")
def test_preview_success(mock_llm, mock_set, mock_get, client):
    mock_llm.return_value = ({"text": "Test answer", "model": "claude-haiku"}, None)
    r = client.post("/preview", json={"topic": "test"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["result"] == "Test answer"
    assert data["free"] is True

@patch("routes.meta._cache_get", return_value=None)
@patch("routes.meta._call_llm")
def test_preview_llm_error(mock_llm, mock_get, client):
    mock_llm.return_value = (None, "LLM failed")
    r = client.post("/preview", json={"topic": "test"})
    assert r.status_code == 400
    assert "error" in r.get_json()

@patch("routes.meta._cache_get")
def test_preview_cached(mock_get, client):
    mock_get.return_value = {"result": "cached", "free": True}
    r = client.post("/preview", json={"topic": "cached topic"})
    assert r.status_code == 200
    assert r.get_json()["result"] == "cached"

def test_preview_get_uses_default_topic(client):
    """GET /preview should use default topic from query param."""
    with patch("routes.meta._cache_get", return_value=None), \
         patch("routes.meta._cache_set"), \
         patch("routes.meta._call_llm", return_value=({"text": "ok", "model": "m"}, None)):
        r = client.get("/preview")
        assert r.status_code == 200


# ── /robots.txt ───────────────────────────────────────────────────────────────

def test_robots_txt(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    body = r.data.decode()
    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Disallow: /admin/" in body
    assert "Sitemap:" in body


# ── /docs ─────────────────────────────────────────────────────────────────────

def test_docs_page(client):
    r = client.get("/docs")
    assert r.status_code == 200


# ── /openapi.json ─────────────────────────────────────────────────────────────

def test_openapi_json(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    data = r.get_json()
    assert "openapi" in data or "paths" in data or "info" in data


# ── /llms.txt ─────────────────────────────────────────────────────────────────

def test_llms_txt(client):
    r = client.get("/llms.txt")
    assert r.status_code == 200
    body = r.data.decode()
    assert "AiPayGen" in body
    assert "text/plain" in r.content_type

def test_llms_txt_contains_key_sections(client):
    r = client.get("/llms.txt")
    body = r.data.decode()
    assert "## Capabilities" in body
    assert "## Authentication" in body
    assert "## Example curl Calls" in body


# ── /.well-known/ai-plugin.json ──────────────────────────────────────────────

def test_ai_plugin_json(client):
    r = client.get("/.well-known/ai-plugin.json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["schema_version"] == "v1"
    assert data["name_for_model"] == "aipaygen"
    assert "api" in data
    assert data["api"]["type"] == "openapi"

def test_ai_plugin_has_auth(client):
    r = client.get("/.well-known/ai-plugin.json")
    data = r.get_json()
    assert data["auth"]["type"] == "service_http"


# ── /.well-known/openapi.json (redirect) ─────────────────────────────────────

def test_well_known_openapi_redirects(client):
    r = client.get("/.well-known/openapi.json")
    assert r.status_code == 301
    assert "/openapi.json" in r.headers.get("Location", "")


# ── /.well-known/agent.json ──────────────────────────────────────────────────

def test_agent_json(client):
    r = client.get("/.well-known/agent.json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["name"] == "AiPayGen"
    assert "capabilities" in data
    assert "skills" in data
    assert isinstance(data["skills"], list)
    assert len(data["skills"]) > 0

def test_agent_json_has_authentication(client):
    r = client.get("/.well-known/agent.json")
    data = r.get_json()
    assert "authentication" in data
    assert "Bearer" in data["authentication"]["schemes"]

def test_agent_json_has_security(client):
    r = client.get("/.well-known/agent.json")
    data = r.get_json()
    assert "security" in data
    assert data["security"]["ssrf_protection"] is True


# ── /.well-known/agents.json ─────────────────────────────────────────────────

def test_agents_json(client):
    r = client.get("/.well-known/agents.json")
    assert r.status_code == 200
    data = r.get_json()
    assert "$schema" in data
    assert "agents" in data
    assert len(data["agents"]) > 0
    agent = data["agents"][0]
    assert agent["name"] == "AiPayGen"
    assert "endpoints" in agent
    assert len(agent["endpoints"]) > 10

def test_agents_json_has_capabilities(client):
    r = client.get("/.well-known/agents.json")
    data = r.get_json()
    agent = data["agents"][0]
    assert "capabilities" in agent
    assert "research" in agent["capabilities"]

def test_agents_json_has_mcp(client):
    r = client.get("/.well-known/agents.json")
    data = r.get_json()
    agent = data["agents"][0]
    assert "mcp" in agent
    assert "remote" in agent["mcp"]


# ── /.well-known/x402.json ───────────────────────────────────────────────────

def test_x402_json(client):
    r = client.get("/.well-known/x402.json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["x402"] is True
    assert "payTo" in data
    assert "network" in data
    assert "endpoints" in data
    assert isinstance(data["endpoints"], list)

def test_x402_json_has_discovery(client):
    r = client.get("/.well-known/x402.json")
    data = r.get_json()
    assert "discovery" in data
    assert "catalog" in data["discovery"]
    assert "openapi" in data["discovery"]


# ── /.well-known/mcp/server-card.json ────────────────────────────────────────

def test_mcp_server_card(client):
    r = client.get("/.well-known/mcp/server-card.json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["serverInfo"]["name"] == "AiPayGen"
    assert "tools" in data
    assert len(data["tools"]) > 5

def test_mcp_server_card_auth_optional(client):
    r = client.get("/.well-known/mcp/server-card.json")
    data = r.get_json()
    assert data["authentication"]["required"] is False


# ── /.well-known/security.txt ────────────────────────────────────────────────

def test_security_txt(client):
    r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Contact:" in body
    assert "text/plain" in r.content_type


# ── /security ─────────────────────────────────────────────────────────────────

def test_security_page(client):
    r = client.get("/security")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Security" in body
    assert "text/html" in r.content_type


# ── /sdk ──────────────────────────────────────────────────────────────────────

def test_sdk_page(client):
    r = client.get("/sdk")
    assert r.status_code == 200
    body = r.data.decode()
    assert "AiPayGen" in body
    assert "text/html" in r.content_type

def test_sdk_cache_control(client):
    r = client.get("/sdk")
    assert "max-age" in r.headers.get("Cache-Control", "")


# ── /sdk/code ─────────────────────────────────────────────────────────────────

def test_sdk_code_python(client):
    r = client.get("/sdk/code?lang=python")
    assert r.status_code == 200
    data = r.get_json()
    assert data["lang"] == "python"
    assert "code" in data
    assert "import" in data["code"]

def test_sdk_code_javascript(client):
    r = client.get("/sdk/code?lang=javascript")
    assert r.status_code == 200
    data = r.get_json()
    assert data["lang"] == "javascript"
    assert "fetch" in data["code"]

def test_sdk_code_curl(client):
    r = client.get("/sdk/code?lang=curl")
    assert r.status_code == 200
    data = r.get_json()
    assert data["lang"] == "curl"
    assert "curl" in data["code"]

def test_sdk_code_unknown_lang(client):
    r = client.get("/sdk/code?lang=brainfuck")
    assert r.status_code == 400
    assert "error" in r.get_json()

def test_sdk_code_custom_endpoint(client):
    r = client.get("/sdk/code?lang=python&endpoint=/summarize")
    assert r.status_code == 200
    data = r.get_json()
    assert data["endpoint"] == "/summarize"
    assert "/summarize" in data["code"]


# ── /sitemap.xml ──────────────────────────────────────────────────────────────

def test_sitemap_xml(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "application/xml" in r.content_type
    body = r.data.decode()
    assert "<urlset" in body
    assert "<url>" in body
    assert "aipaygen.com" in body

def test_sitemap_includes_key_pages(client):
    r = client.get("/sitemap.xml")
    body = r.data.decode()
    assert "/discover" in body
    assert "/docs" in body
    assert "/security" in body


# ── /discover ─────────────────────────────────────────────────────────────────

def test_discover_json(client):
    """Agent request (Accept: application/json) should get JSON catalog."""
    r = client.get("/discover", headers={"Accept": "application/json"})
    assert r.status_code == 200
    data = r.get_json()
    assert "categories" in data
    assert "payment" in data
    assert "meta" in data

def test_discover_html(client):
    """Browser request should get HTML."""
    r = client.get("/discover", headers={"Accept": "text/html"})
    assert r.status_code == 200

def test_discover_json_has_payment_info(client):
    r = client.get("/discover", headers={"Accept": "application/json"})
    data = r.get_json()
    assert "recommended" in data["payment"]
    assert "x402" in data["payment"]
    assert "mcp" in data["payment"]


# ── /try ──────────────────────────────────────────────────────────────────────

def test_try_page(client):
    r = client.get("/try")
    assert r.status_code == 200
    assert "text/html" in r.content_type


# ── /try/<tool> ───────────────────────────────────────────────────────────────

@patch("routes.meta._check_demo_limit", return_value=True)
def test_try_tool_unknown(mock_limit, client):
    r = client.post("/try/nonexistent_tool_xyz", json={})
    assert r.status_code == 400
    assert "Unknown demo tool" in r.get_json()["error"]

@patch("routes.meta._check_demo_limit", return_value=False)
def test_try_tool_rate_limited(mock_limit, client):
    r = client.post("/try/sentiment", json={"text": "hello"})
    assert r.status_code == 429
    assert "limit" in r.get_json()["error"].lower()

@patch("routes.meta._check_demo_limit", return_value=True)
@patch("routes.meta.sentiment_inner", create=True)
def test_try_sentiment(mock_inner, mock_limit, client):
    # Import at call time inside the route, so we patch the actual import path
    with patch("routes.ai_tools.sentiment_inner", return_value={"sentiment": "positive", "score": 0.9}):
        r = client.post("/try/sentiment", json={"text": "I love this"})
        assert r.status_code == 200
        data = r.get_json()
        assert "result" in data
        assert data["tool"] == "sentiment"

@patch("routes.meta._check_demo_limit", return_value=True)
def test_try_geocode_proxies(mock_limit, client):
    with patch("routes.meta._requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"lat": 40.7, "lon": -74.0}
        mock_get.return_value = mock_resp
        r = client.post("/try/geocode", json={"q": "New York"})
        assert r.status_code == 200

@patch("routes.meta._check_demo_limit", return_value=True)
def test_try_tool_exception(mock_limit, client):
    """If the tool throws an exception, should return 500."""
    with patch("routes.ai_tools.sentiment_inner", side_effect=Exception("boom")):
        r = client.post("/try/sentiment", json={"text": "test"})
        assert r.status_code == 500
        assert "boom" in r.get_json()["error"]


# ── _check_demo_limit ────────────────────────────────────────────────────────

def test_demo_limit_allows_under_limit():
    from routes.meta import _check_demo_limit, _demo_usage
    test_ip = "test_ip_999"
    _demo_usage.pop(f"demo:{test_ip}", None)
    for _ in range(10):
        assert _check_demo_limit(test_ip) is True
    assert _check_demo_limit(test_ip) is False
    # Cleanup
    _demo_usage.pop(f"demo:{test_ip}", None)


# ── _build_discover_services ─────────────────────────────────────────────────

def test_build_discover_services():
    from routes.meta import _build_discover_services
    cats = _build_discover_services()
    assert isinstance(cats, dict)
    assert len(cats) > 0
    for cat_name, services in cats.items():
        assert isinstance(services, list)
        for s in services:
            assert "endpoint" in s
            assert "method" in s
            assert "description" in s
