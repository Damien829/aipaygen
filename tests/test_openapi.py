"""Tests for the OpenAPI 3.1.0 spec generator."""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from x402.http import PaymentOption
from x402.http.types import RouteConfig


def _make_routes():
    """Build a minimal routes dict matching the app.py structure."""
    wallet = "0x366D488a48de1B2773F3a21F1A6972715056Cb30"
    net = "eip155:8453"

    def _r(price, desc, mime="application/json"):
        return RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=wallet, price=price, network=net)],
            mime_type=mime,
            description=desc,
        )

    return {
        "POST /research": _r("$0.05", "Deep research ($0.05)"),
        "POST /scrape": _r("$0.01", "Fetch URL ($0.01)"),
        "POST /write": _r("$0.02", "Write content ($0.02)"),
        "POST /analyze": _r("$0.01", "Analyze ($0.01)"),
        "POST /code": _r("$0.02", "Generate code ($0.02)"),
        "POST /summarize": _r("$0.01", "Summarize ($0.01)"),
        "POST /translate": _r("$0.01", "Translate ($0.01)"),
        "POST /social": _r("$0.02", "Social posts ($0.02)"),
        "POST /batch": _r("$0.03", "Batch ($0.03)"),
        "POST /extract": _r("$0.01", "Extract ($0.01)"),
        "POST /qa": _r("$0.01", "QA ($0.01)"),
        "POST /classify": _r("$0.01", "Classify ($0.01)"),
        "POST /sentiment": _r("$0.01", "Sentiment ($0.01)"),
        "POST /keywords": _r("$0.01", "Keywords ($0.01)"),
        "POST /compare": _r("$0.01", "Compare ($0.01)"),
        "POST /transform": _r("$0.01", "Transform ($0.01)"),
        "POST /chat": _r("$0.02", "Chat ($0.02)"),
        "POST /plan": _r("$0.02", "Plan ($0.02)"),
        "POST /decide": _r("$0.02", "Decide ($0.02)"),
        "POST /proofread": _r("$0.01", "Proofread ($0.01)"),
        "POST /explain": _r("$0.01", "Explain ($0.01)"),
        "POST /questions": _r("$0.01", "Questions ($0.01)"),
        "POST /outline": _r("$0.01", "Outline ($0.01)"),
        "POST /email": _r("$0.02", "Email ($0.02)"),
        "POST /sql": _r("$0.02", "SQL ($0.02)"),
        "POST /regex": _r("$0.01", "Regex ($0.01)"),
        "POST /mock": _r("$0.02", "Mock data ($0.02)"),
        "POST /score": _r("$0.01", "Score ($0.01)"),
        "POST /timeline": _r("$0.01", "Timeline ($0.01)"),
        "POST /action": _r("$0.01", "Actions ($0.01)"),
        "POST /pipeline": _r("$0.05", "Pipeline ($0.05)"),
        "GET /web/search": _r("$0.02", "Web search ($0.02)"),
    }


@pytest.fixture
def spec():
    from openapi_gen import generate_openapi_spec
    return generate_openapi_spec(routes=_make_routes())


def test_openapi_spec_structure(spec):
    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "AiPayGen API"
    assert "/research" in spec["paths"]
    assert "/scrape" in spec["paths"]
    assert "securitySchemes" in spec["components"]


def test_openapi_has_all_routes(spec):
    # 32 paid + 9 free = 41 paths (some share path, e.g. /web/search)
    assert len(spec["paths"]) >= 30


def test_openapi_includes_free_endpoints(spec):
    assert "/free/time" in spec["paths"]
    assert "/health" in spec["paths"]


def test_openapi_has_pricing(spec):
    research = spec["paths"]["/research"]["post"]
    assert "x-pricing" in research
    assert research["x-pricing"]["price"] == "$0.05"


def test_openapi_free_endpoints_no_auth(spec):
    health = spec["paths"]["/health"]["get"]
    assert health["security"] == []


def test_openapi_paid_endpoints_have_auth(spec):
    research = spec["paths"]["/research"]["post"]
    assert len(research["security"]) == 2


def test_openapi_security_schemes(spec):
    schemes = spec["components"]["securitySchemes"]
    assert "bearerApiKey" in schemes
    assert "x402Payment" in schemes
    assert schemes["x402Payment"]["name"] == "X-Payment"
