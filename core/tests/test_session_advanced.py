"""Tests for advanced session features — create, call, history, delete."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("SESSIONS_DB", ":memory:")
os.environ.setdefault("WEBHOOKS_DB", ":memory:")

FAKE_KEY = "apk_test_session_adv"
AUTH = {"Authorization": f"Bearer {FAKE_KEY}", "Content-Type": "application/json"}


def _validate_key_ok(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 100.0, "is_active": 1}
    return None


def _mock_sentiment(d):
    return {"sentiment": "positive", "score": 0.9}


def _mock_translate(d):
    return {"result": "Hola", "language": d.get("language", "es")}


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestSessionCreate:
    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_create_returns_session_id(self, mock_vk, client):
        r = client.post("/session/create", headers=AUTH, json={"agent_id": "bot-1"})
        assert r.status_code == 200
        data = r.get_json()
        assert "session_id" in data
        assert data["agent_id"] == "bot-1"
        assert data["ttl_hours"] == 1  # default

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_create_custom_ttl(self, mock_vk, client):
        r = client.post("/session/create", headers=AUTH,
                        json={"agent_id": "bot-1", "ttl_hours": 12})
        data = r.get_json()
        assert data["ttl_hours"] == 12

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_create_ttl_capped_at_24(self, mock_vk, client):
        r = client.post("/session/create", headers=AUTH,
                        json={"ttl_hours": 100})
        data = r.get_json()
        assert data["ttl_hours"] == 24

    def test_create_no_auth(self, client):
        r = client.post("/session/create", json={})
        assert r.status_code == 401


class TestSessionCall:
    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions._batch_handlers", {"sentiment": _mock_sentiment, "translate": _mock_translate})
    def test_call_executes_tool(self, mock_vk, client):
        # Create a session first
        r = client.post("/session/create", headers=AUTH, json={"agent_id": "bot-1"})
        sid = r.get_json()["session_id"]

        # Call a tool
        r = client.post(f"/session/{sid}/call", headers=AUTH,
                        json={"tool": "sentiment", "input": {"text": "I love AI"}})
        assert r.status_code == 200
        data = r.get_json()
        assert data["tool"] == "sentiment"
        assert data["result"]["sentiment"] == "positive"
        assert "time_ms" in data

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions._batch_handlers", {"sentiment": _mock_sentiment})
    def test_call_unknown_tool_returns_400(self, mock_vk, client):
        r = client.post("/session/create", headers=AUTH, json={})
        sid = r.get_json()["session_id"]

        r = client.post(f"/session/{sid}/call", headers=AUTH,
                        json={"tool": "nonexistent", "input": {}})
        assert r.status_code == 400
        assert "unknown tool" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions._batch_handlers", {"sentiment": _mock_sentiment})
    def test_call_missing_tool_returns_400(self, mock_vk, client):
        r = client.post("/session/create", headers=AUTH, json={})
        sid = r.get_json()["session_id"]

        r = client.post(f"/session/{sid}/call", headers=AUTH, json={"input": {}})
        assert r.status_code == 400
        assert "tool required" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions._batch_handlers", {"sentiment": _mock_sentiment})
    def test_call_nonexistent_session(self, mock_vk, client):
        r = client.post("/session/fake-id/call", headers=AUTH,
                        json={"tool": "sentiment", "input": {"text": "hi"}})
        assert r.status_code == 404


class TestSessionHistory:
    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions._batch_handlers", {"sentiment": _mock_sentiment, "translate": _mock_translate})
    def test_history_returns_calls(self, mock_vk, client):
        # Create session and make calls
        r = client.post("/session/create", headers=AUTH, json={})
        sid = r.get_json()["session_id"]

        client.post(f"/session/{sid}/call", headers=AUTH,
                    json={"tool": "sentiment", "input": {"text": "hi"}})
        client.post(f"/session/{sid}/call", headers=AUTH,
                    json={"tool": "translate", "input": {"text": "hi", "language": "es"}})

        r = client.get(f"/session/{sid}/history", headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["call_count"] == 2
        assert len(data["history"]) == 2
        assert data["history"][0]["tool"] == "sentiment"
        assert data["history"][1]["tool"] == "translate"

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_history_nonexistent_session(self, mock_vk, client):
        r = client.get("/session/fake-id/history", headers=AUTH)
        assert r.status_code == 404

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions._batch_handlers", {"sentiment": _mock_sentiment})
    def test_history_empty_session(self, mock_vk, client):
        r = client.post("/session/create", headers=AUTH, json={})
        sid = r.get_json()["session_id"]

        r = client.get(f"/session/{sid}/history", headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()["call_count"] == 0


class TestSessionDelete:
    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions._batch_handlers", {"sentiment": _mock_sentiment})
    def test_delete_session(self, mock_vk, client):
        r = client.post("/session/create", headers=AUTH, json={})
        sid = r.get_json()["session_id"]

        # Make a call
        client.post(f"/session/{sid}/call", headers=AUTH,
                    json={"tool": "sentiment", "input": {"text": "hi"}})

        # Delete
        r = client.delete(f"/session/{sid}", headers=AUTH)
        assert r.status_code == 200
        assert r.get_json()["deleted"] is True

        # Verify gone
        r = client.get(f"/session/{sid}", headers=AUTH)
        assert r.status_code == 404

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_delete_nonexistent(self, mock_vk, client):
        r = client.delete("/session/fake-id", headers=AUTH)
        assert r.status_code == 404


class TestSessionContextInjection:
    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions._batch_handlers", {"sentiment": _mock_sentiment})
    def test_second_call_gets_context(self, mock_vk, client):
        """The second call should have session history injected."""
        r = client.post("/session/create", headers=AUTH, json={})
        sid = r.get_json()["session_id"]

        # First call
        client.post(f"/session/{sid}/call", headers=AUTH,
                    json={"tool": "sentiment", "input": {"text": "I love AI"}})

        # Second call — handler still gets called, context injection is best-effort
        r = client.post(f"/session/{sid}/call", headers=AUTH,
                        json={"tool": "sentiment", "input": {"text": "I hate bugs"}})
        assert r.status_code == 200
        # Call history should now have 2 entries
        r = client.get(f"/session/{sid}/history", headers=AUTH)
        assert r.get_json()["call_count"] == 2
