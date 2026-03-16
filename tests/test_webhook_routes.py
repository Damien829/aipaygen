"""Tests for the webhook testing UI routes and new webhook endpoints."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("WEBHOOKS_DB", ":memory:")

import pytest
from unittest.mock import patch

FAKE_KEY = "apk_test_wh_routes"
AUTH = {"Authorization": f"Bearer {FAKE_KEY}", "Content-Type": "application/json"}


def _validate_key_ok(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 100.0, "is_active": 1}
    return None


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestWebhookTestPage:
    def test_page_renders(self, client):
        r = client.get("/webhooks/test")
        assert r.status_code == 200
        assert b"Webhook" in r.data

    def test_page_with_key(self, client):
        r = client.get("/webhooks/test?key=apk_test123")
        assert r.status_code == 200


class TestWebhookTestEvent:
    def test_no_auth(self, client):
        r = client.post("/webhooks/test-event", json={"event": "low_balance"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_send_test_event(self, mock_vk, client):
        r = client.post("/webhooks/test-event", headers=AUTH,
                        json={"event": "low_balance", "payload": {"test": True}})
        assert r.status_code == 200
        data = r.get_json()
        assert "dispatched_to" in data
        assert data["event"] == "low_balance"


class TestWebhookDeliveries:
    def test_no_auth(self, client):
        r = client.get("/webhooks/deliveries")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_deliveries(self, mock_vk, client):
        r = client.get("/webhooks/deliveries", headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert "deliveries" in data
        assert isinstance(data["deliveries"], list)

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_deliveries_with_limit(self, mock_vk, client):
        r = client.get("/webhooks/deliveries?limit=10", headers=AUTH)
        assert r.status_code == 200


class TestWebhookDispatchDeliveryLog:
    def test_get_deliveries_after_dispatch(self):
        from webhook_dispatch import register_webhook, get_deliveries, dispatch_test_event
        api_key = "apk_delivery_log_test"
        register_webhook(api_key, "https://httpbin.org/post", ["low_balance"])
        count = dispatch_test_event("low_balance", api_key, {"test": True})
        assert count == 1
        deliveries = get_deliveries(api_key)
        assert len(deliveries) >= 1
        assert deliveries[0]["event"] == "low_balance"

    def test_get_deliveries_empty(self):
        from webhook_dispatch import get_deliveries
        deliveries = get_deliveries("apk_nonexistent_key")
        assert deliveries == []


class TestDocsErrorCodes:
    def test_docs_has_error_codes_section(self, client):
        r = client.get("/docs")
        assert r.status_code == 200
        body = r.data
        assert b"Error Codes Reference" in body
        assert b"400" in body
        assert b"401" in body
        assert b"402" in body
        assert b"403" in body
        assert b"429" in body
        assert b"500" in body
        assert b"503" in body

    def test_docs_has_retry_after_info(self, client):
        r = client.get("/docs")
        assert b"retry_after" in r.data

    def test_docs_has_request_id(self, client):
        r = client.get("/docs")
        assert b"request_id" in r.data

    def test_docs_has_webhooks_section(self, client):
        r = client.get("/docs")
        assert b"id=\"webhooks\"" in r.data
        assert b"/webhooks/register" in r.data
        assert b"/webhooks/test-event" in r.data
        assert b"/webhooks/deliveries" in r.data


class TestDiscoverEnhanced:
    def test_discover_has_data_attributes(self, client):
        r = client.get("/discover", headers={"Accept": "text/html"})
        assert r.status_code == 200
        assert b"data-method" in r.data
        assert b"data-price" in r.data
        assert b"data-path" in r.data

    def test_discover_has_curl_section(self, client):
        r = client.get("/discover", headers={"Accept": "text/html"})
        assert b"demoCurl" in r.data
        assert b"demoCurlCode" in r.data

    def test_discover_has_cost_badge(self, client):
        r = client.get("/discover", headers={"Accept": "text/html"})
        assert b"demoCost" in r.data

    def test_discover_has_tool_fields(self, client):
        r = client.get("/discover", headers={"Accept": "text/html"})
        assert b"toolFields" in r.data
        assert b"demoFields" in r.data

    def test_discover_json_still_works(self, client):
        r = client.get("/discover", headers={"Accept": "application/json"})
        assert r.status_code == 200
        data = r.get_json()
        assert "meta" in data
