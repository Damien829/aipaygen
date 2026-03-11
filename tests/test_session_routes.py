"""Comprehensive tests for session route endpoints in routes/sessions.py."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("WEBHOOKS_DB", ":memory:")

FAKE_KEY = "apk_test_session_key"
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


# ── POST /session/start ────────────────────────────────────────────────────

class TestSessionStart:
    def test_no_auth(self, client):
        r = client.post("/session/start", json={"agent_id": "a"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions.create_session", return_value="sess-12345")
    def test_success(self, mock_create, mock_vk, client):
        r = client.post("/session/start", headers=AUTH,
                        json={"agent_id": "agent-a", "context": {"topic": "AI"}, "ttl_hours": 48})
        assert r.status_code == 200
        data = r.get_json()
        assert data["session_id"] == "sess-12345"
        assert data["ttl_hours"] == 48
        mock_create.assert_called_once_with(agent_id="agent-a", context={"topic": "AI"}, ttl_hours=48)

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions.create_session", return_value="sess-default")
    def test_defaults(self, mock_create, mock_vk, client):
        r = client.post("/session/start", headers=AUTH, json={})
        assert r.status_code == 200
        data = r.get_json()
        assert data["ttl_hours"] == 24
        mock_create.assert_called_once_with(agent_id="anonymous", context={}, ttl_hours=24)

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions.create_session", return_value="sess-nobody")
    def test_no_body(self, mock_create, mock_vk, client):
        """POST with no JSON body should use defaults."""
        r = client.post("/session/start", headers=AUTH,
                        content_type="application/json", data="{}")
        assert r.status_code == 200


# ── GET /session/<session_id> ──────────────────────────────────────────────

class TestSessionGet:
    def test_no_auth(self, client):
        r = client.get("/session/sess-12345")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions.get_session", return_value={
        "session_id": "sess-1", "agent_id": "agent-a",
        "context": {"topic": "AI"}, "created_at": "2026-01-01"
    })
    def test_success(self, mock_get, mock_vk, client):
        r = client.get("/session/sess-1", headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["session_id"] == "sess-1"
        assert data["agent_id"] == "agent-a"

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions.get_session", return_value=None)
    def test_not_found(self, mock_get, mock_vk, client):
        r = client.get("/session/nonexistent-sess", headers=AUTH)
        assert r.status_code == 404
        assert r.get_json()["error"] == "session_not_found"


# ── PUT /session/<session_id>/context ──────────────────────────────────────

class TestSessionUpdateContext:
    def test_no_auth(self, client):
        r = client.put("/session/sess-1/context", json={"context": {"new": "data"}})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions.get_session", return_value={
        "session_id": "sess-1", "agent_id": "agent-a",
        "context": {"topic": "AI"}, "created_at": "2026-01-01"
    })
    @patch("routes.sessions.update_session_context")
    def test_success(self, mock_update, mock_get, mock_vk, client):
        r = client.put("/session/sess-1/context", headers=AUTH,
                       json={"context": {"history": ["msg1"]}})
        assert r.status_code == 200
        data = r.get_json()
        assert data["session_id"] == "sess-1"
        # Should merge existing context with new context
        assert "topic" in data["context"]
        assert "history" in data["context"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions.get_session", return_value=None)
    def test_not_found(self, mock_get, mock_vk, client):
        r = client.put("/session/nonexistent/context", headers=AUTH,
                       json={"context": {"new": "data"}})
        assert r.status_code == 404
        assert r.get_json()["error"] == "session_not_found"

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.sessions.get_session", return_value={
        "session_id": "sess-2", "agent_id": "a",
        "context": {"old": "data"}, "created_at": "2026-01-01"
    })
    @patch("routes.sessions.update_session_context")
    def test_empty_context_merge(self, mock_update, mock_get, mock_vk, client):
        """Empty new context should preserve existing context."""
        r = client.put("/session/sess-2/context", headers=AUTH, json={})
        assert r.status_code == 200
        data = r.get_json()
        assert data["context"]["old"] == "data"
