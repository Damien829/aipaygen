"""Tests for /discover competitive protection and discovery endpoints."""
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


def test_discover_json_no_service_count():
    """Public /discover JSON meta must not expose total_services or free_count."""
    from app import app
    client = app.test_client()
    resp = client.get("/discover", headers={"Accept": "application/json"})
    data = json.loads(resp.data)

    assert "total_services" not in data.get("meta", {})
    assert "free_count" not in data.get("meta", {})


def test_agent_json_no_pricing_breakdown():
    """agent.json must not expose detailed pricing tiers."""
    from app import app
    client = app.test_client()
    resp = client.get("/.well-known/agent.json")
    data = json.loads(resp.data)

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
    assert "x402" in str(data)


def test_docs_page_exists():
    """GET /docs returns HTML with integration guide."""
    from app import app
    client = app.test_client()
    resp = client.get("/docs")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "x402" in html


def test_skills_search_requires_auth():
    """GET /skills/search requires admin auth."""
    from app import app
    client = app.test_client()
    resp = client.get("/skills/search?q=python")
    assert resp.status_code in (401, 403), \
        f"Expected 401/403, got {resp.status_code}"
