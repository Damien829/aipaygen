"""Comprehensive tests for memory endpoints in routes/agent.py — JWT auth and ownership checks."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("WEBHOOKS_DB", ":memory:")

FAKE_JWT = "eyJfake.jwt.token"
JWT_HEADER = {"Authorization": f"Bearer {FAKE_JWT}", "Content-Type": "application/json"}
JWT_PAYLOAD = {"agent_id": "agent-a", "wallet_address": "0x123"}


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── POST /memory/set ───────────────────────────────────────────────────────

class TestMemorySet:
    def test_no_auth(self, client):
        r = client.post("/memory/set",
                        json={"agent_id": "a", "key": "k", "value": "v"},
                        content_type="application/json")
        assert r.status_code == 401

    def test_api_key_not_enough(self, client):
        """Memory set requires JWT, not API key."""
        r = client.post("/memory/set",
                        headers={"Authorization": "Bearer apk_test_key"},
                        json={"agent_id": "a", "key": "k", "value": "v"})
        assert r.status_code == 401

    @patch("routes.agent.verify_jwt", return_value=JWT_PAYLOAD)
    @patch("routes.agent.memory_set", return_value={"key": "k", "stored": True})
    @patch("routes.agent.log_payment")
    def test_success(self, mock_log, mock_set, mock_jwt, client):
        r = client.post("/memory/set", headers=JWT_HEADER,
                        json={"agent_id": "agent-a", "key": "settings", "value": {"theme": "dark"}})
        assert r.status_code == 200
        data = r.get_json()
        assert data["stored"] is True

    @patch("routes.agent.verify_jwt", return_value=JWT_PAYLOAD)
    def test_missing_key(self, mock_jwt, client):
        r = client.post("/memory/set", headers=JWT_HEADER,
                        json={"agent_id": "agent-a", "value": "test"})
        assert r.status_code == 400

    @patch("routes.agent.verify_jwt", return_value=JWT_PAYLOAD)
    def test_missing_value(self, mock_jwt, client):
        r = client.post("/memory/set", headers=JWT_HEADER,
                        json={"agent_id": "agent-a", "key": "k"})
        assert r.status_code == 400


# ── POST /memory/get ───────────────────────────────────────────────────────

class TestMemoryGet:
    def test_no_auth(self, client):
        r = client.post("/memory/get", json={"key": "k"},
                        content_type="application/json")
        assert r.status_code == 401

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    @patch("routes.agent.memory_get", return_value={"key": "k", "value": "v"})
    @patch("routes.agent.log_payment")
    def test_success(self, mock_log, mock_get, mock_jwt, client):
        r = client.post("/memory/get", headers=JWT_HEADER,
                        json={"agent_id": "agent-a", "key": "settings"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["key"] == "k"

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    def test_ownership_mismatch(self, mock_jwt, client):
        """Agent-a's JWT should not access agent-b's memory."""
        r = client.post("/memory/get", headers=JWT_HEADER,
                        json={"agent_id": "agent-b", "key": "secret"})
        assert r.status_code == 403
        assert "forbidden" in r.get_json()["error"]

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    def test_missing_key(self, mock_jwt, client):
        r = client.post("/memory/get", headers=JWT_HEADER, json={"agent_id": "agent-a"})
        assert r.status_code == 400

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    @patch("routes.agent.memory_get", return_value=None)
    @patch("routes.agent.log_payment")
    def test_not_found(self, mock_log, mock_get, mock_jwt, client):
        r = client.post("/memory/get", headers=JWT_HEADER,
                        json={"agent_id": "agent-a", "key": "nonexistent"})
        assert r.status_code == 404


# ── POST /memory/search ───────────────────────────────────────────────────

class TestMemorySearch:
    def test_no_auth(self, client):
        r = client.post("/memory/search", json={"query": "test"},
                        content_type="application/json")
        assert r.status_code == 401

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    @patch("routes.agent.memory_search", return_value=[{"key": "k1", "value": "v1"}])
    @patch("routes.agent.log_payment")
    def test_success(self, mock_log, mock_search, mock_jwt, client):
        r = client.post("/memory/search", headers=JWT_HEADER,
                        json={"agent_id": "agent-a", "query": "settings"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    def test_ownership_mismatch(self, mock_jwt, client):
        r = client.post("/memory/search", headers=JWT_HEADER,
                        json={"agent_id": "agent-b", "query": "secrets"})
        assert r.status_code == 403

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    def test_missing_query(self, mock_jwt, client):
        r = client.post("/memory/search", headers=JWT_HEADER,
                        json={"agent_id": "agent-a"})
        assert r.status_code == 400
        assert "query" in r.get_json()["error"]


# ── POST /memory/list ──────────────────────────────────────────────────────

class TestMemoryList:
    def test_no_auth(self, client):
        r = client.post("/memory/list", json={"agent_id": "a"},
                        content_type="application/json")
        assert r.status_code == 401

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    @patch("routes.agent.memory_list", return_value=["key1", "key2", "key3"])
    @patch("routes.agent.log_payment")
    def test_success(self, mock_log, mock_list, mock_jwt, client):
        r = client.post("/memory/list", headers=JWT_HEADER,
                        json={"agent_id": "agent-a"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 3

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    def test_ownership_mismatch(self, mock_jwt, client):
        r = client.post("/memory/list", headers=JWT_HEADER,
                        json={"agent_id": "agent-b"})
        assert r.status_code == 403

    @patch("agent_identity.verify_jwt", return_value=JWT_PAYLOAD)
    @patch("routes.agent.memory_list", return_value=[])
    @patch("routes.agent.log_payment")
    def test_empty_list(self, mock_log, mock_list, mock_jwt, client):
        r = client.post("/memory/list", headers=JWT_HEADER,
                        json={"agent_id": "agent-a"})
        assert r.status_code == 200
        assert r.get_json()["count"] == 0


# ── POST /memory/clear ────────────────────────────────────────────────────

class TestMemoryClear:
    def test_no_auth(self, client):
        r = client.post("/memory/clear", json={"agent_id": "a"},
                        content_type="application/json")
        assert r.status_code == 401

    @patch("routes.agent.verify_jwt", return_value=JWT_PAYLOAD)
    @patch("routes.agent.memory_clear", return_value=5)
    @patch("routes.agent.log_payment")
    def test_success(self, mock_log, mock_clear, mock_jwt, client):
        r = client.post("/memory/clear", headers=JWT_HEADER,
                        json={"agent_id": "agent-a"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["deleted"] == 5

    def test_api_key_not_enough(self, client):
        r = client.post("/memory/clear",
                        headers={"Authorization": "Bearer apk_test_key"},
                        json={"agent_id": "a"})
        assert r.status_code == 401
