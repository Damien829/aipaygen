"""Tests for pricing restructure — data endpoints are paid, honeypots are free."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__) + "/..")

def test_free_tier_only_honeypots():
    """Only specific honeypot endpoints should be free ($0.00)."""
    from routes.meta import _build_discover_services
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
    from routes.meta import _build_discover_services
    categories = _build_discover_services()
    data_services = categories.get("Data & Utilities", [])

    for svc in data_services:
        if svc["endpoint"].startswith("/free/"):
            continue
        assert svc["price_usd"] >= 0.01, \
            f"{svc['endpoint']} should be paid, got ${svc['price_usd']}"
