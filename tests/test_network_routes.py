"""Comprehensive tests for routes/network.py — all 12 network endpoints."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("WEBHOOKS_DB", ":memory:")

FAKE_KEY = "apk_test_network_key"
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


# ── POST /message/send ─────────────────────────────────────────────────────

class TestMessageSend:
    def test_no_auth(self, client):
        r = client.post("/message/send", json={"from_agent": "a", "to_agent": "b", "body": "hi"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.send_message", return_value={"msg_id": "m1", "status": "sent"})
    @patch("routes.network.log_payment")
    def test_success(self, mock_log, mock_send, mock_vk, client):
        r = client.post("/message/send", headers=AUTH,
                        json={"from_agent": "agent-a", "to_agent": "agent-b", "body": "hello"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["msg_id"] == "m1"
        mock_send.assert_called_once()

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_fields(self, mock_vk, client):
        r = client.post("/message/send", headers=AUTH, json={"from_agent": "a"})
        assert r.status_code == 400
        assert "required" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_empty_body(self, mock_vk, client):
        r = client.post("/message/send", headers=AUTH,
                        json={"from_agent": "a", "to_agent": "b", "body": ""})
        assert r.status_code == 400


# ── GET /message/inbox/<agent_id> ──────────────────────────────────────────

class TestMessageInbox:
    def test_no_auth(self, client):
        r = client.get("/message/inbox/agent-a")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_no_jwt(self, mock_vk, client):
        """API key alone is not enough — need JWT for inbox."""
        r = client.get("/message/inbox/agent-a", headers=AUTH)
        assert r.status_code == 401
        assert "JWT" in r.get_json().get("message", "")

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.verify_jwt", return_value={"agent_id": "agent-a"})
    @patch("routes.network.get_inbox", return_value=[{"msg_id": "m1", "body": "hi"}])
    def test_success_with_jwt(self, mock_inbox, mock_jwt, mock_vk, client):
        r = client.get("/message/inbox/agent-a",
                       headers={"Authorization": "Bearer apk_test_net",
                                "Content-Type": "application/json"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1
        assert data["agent_id"] == "agent-a"

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.verify_jwt", return_value={"agent_id": "agent-b"})
    def test_wrong_agent_jwt(self, mock_jwt, mock_vk, client):
        """JWT for agent-b trying to access agent-a inbox."""
        r = client.get("/message/inbox/agent-a",
                       headers={"Authorization": "Bearer eyJfake.token.here"})
        assert r.status_code == 401


# ── POST /message/reply ────────────────────────────────────────────────────

class TestMessageReply:
    def test_no_auth(self, client):
        r = client.post("/message/reply", json={"msg_id": "m1", "from_agent": "a", "body": "ok"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_fields(self, mock_vk, client):
        r = client.post("/message/reply", headers=AUTH, json={"msg_id": "m1"})
        assert r.status_code == 400

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.send_message", return_value={"msg_id": "m2", "status": "sent"})
    @patch("routes.network.get_inbox", return_value=[])
    @patch("routes.network.log_payment")
    def test_success(self, mock_log, mock_inbox, mock_send, mock_vk, client):
        r = client.post("/message/reply", headers=AUTH,
                        json={"msg_id": "m1", "from_agent": "a", "to_agent": "b", "body": "reply"})
        assert r.status_code == 200


# ── POST /message/broadcast ────────────────────────────────────────────────

class TestMessageBroadcast:
    def test_no_auth(self, client):
        r = client.post("/message/broadcast", json={"from_agent": "a", "body": "hello all"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_fields(self, mock_vk, client):
        r = client.post("/message/broadcast", headers=AUTH, json={"from_agent": "a"})
        assert r.status_code == 400

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.broadcast_message", return_value={"sent_to": 5})
    @patch("routes.network.log_payment")
    def test_success(self, mock_log, mock_bc, mock_vk, client):
        r = client.post("/message/broadcast", headers=AUTH,
                        json={"from_agent": "a", "body": "announcement"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["broadcast"] is True


# ── POST /message/mark-read ────────────────────────────────────────────────

class TestMessageMarkRead:
    def test_no_auth(self, client):
        r = client.post("/message/mark-read", json={"msg_id": "m1", "agent_id": "a"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_fields(self, mock_vk, client):
        r = client.post("/message/mark-read", headers=AUTH, json={"msg_id": "m1"})
        assert r.status_code == 400

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_no_jwt_for_mark_read(self, mock_vk, client):
        """Requires JWT to verify agent ownership."""
        r = client.post("/message/mark-read", headers=AUTH,
                        json={"msg_id": "m1", "agent_id": "a"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.verify_jwt", return_value={"agent_id": "agent-a"})
    @patch("routes.network.mark_read", return_value=True)
    def test_success_with_jwt(self, mock_mark, mock_jwt, mock_vk, client):
        r = client.post("/message/mark-read",
                        headers={"Authorization": "Bearer apk_test_net",
                                 "Content-Type": "application/json"},
                        json={"msg_id": "m1", "agent_id": "agent-a"})
        assert r.status_code == 200
        assert r.get_json()["marked_read"] is True


# ── POST /knowledge/add ────────────────────────────────────────────────────

class TestKnowledgeAdd:
    def test_no_auth(self, client):
        r = client.post("/knowledge/add", json={"topic": "t", "content": "c"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_fields(self, mock_vk, client):
        r = client.post("/knowledge/add", headers=AUTH, json={"topic": "t"})
        assert r.status_code == 400

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.add_knowledge", return_value={"id": "k1", "topic": "AI"})
    @patch("routes.network.log_payment")
    def test_success(self, mock_log, mock_add, mock_vk, client):
        r = client.post("/knowledge/add", headers=AUTH,
                        json={"topic": "AI", "content": "Neural nets are cool", "tags": ["ml", "ai"]})
        assert r.status_code == 200
        assert r.get_json()["id"] == "k1"

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.add_knowledge", return_value={"id": "k2", "topic": "X"})
    @patch("routes.network.log_payment")
    def test_tags_as_csv_string(self, mock_log, mock_add, mock_vk, client):
        r = client.post("/knowledge/add", headers=AUTH,
                        json={"topic": "X", "content": "content", "tags": "a, b, c"})
        assert r.status_code == 200


# ── GET /knowledge/search ──────────────────────────────────────────────────

class TestKnowledgeSearch:
    def test_no_auth(self, client):
        r = client.get("/knowledge/search?q=test")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_query(self, mock_vk, client):
        r = client.get("/knowledge/search", headers=AUTH)
        assert r.status_code == 400
        assert "q" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.search_knowledge", return_value=[{"id": "k1", "topic": "AI"}])
    def test_success(self, mock_search, mock_vk, client):
        r = client.get("/knowledge/search?q=AI", headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1
        assert data["query"] == "AI"


# ── POST /knowledge/vote ──────────────────────────────────────────────────

class TestKnowledgeVote:
    def test_no_auth(self, client):
        r = client.post("/knowledge/vote", json={"entry_id": "k1"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_entry_id(self, mock_vk, client):
        r = client.post("/knowledge/vote", headers=AUTH, json={})
        assert r.status_code == 400

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.vote_knowledge", return_value={"entry_id": "k1", "upvotes": 5})
    def test_success(self, mock_vote, mock_vk, client):
        r = client.post("/knowledge/vote", headers=AUTH, json={"entry_id": "k1", "up": True})
        assert r.status_code == 200
        assert r.get_json()["upvotes"] == 5


# ── POST /task/submit ──────────────────────────────────────────────────────

class TestTaskSubmit:
    def test_no_auth(self, client):
        r = client.post("/task/submit", json={"posted_by": "a", "title": "t", "description": "d"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_fields(self, mock_vk, client):
        r = client.post("/task/submit", headers=AUTH, json={"posted_by": "a"})
        assert r.status_code == 400

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.submit_task", return_value={"task_id": "t1", "status": "open"})
    @patch("routes.network.log_payment")
    def test_success(self, mock_log, mock_submit, mock_vk, client):
        r = client.post("/task/submit", headers=AUTH,
                        json={"posted_by": "agent-a", "title": "Fix bug",
                              "description": "Fix the login bug", "reward_usd": 1.0})
        assert r.status_code == 200
        assert r.get_json()["task_id"] == "t1"


# ── GET /task/browse ───────────────────────────────────────────────────────

class TestTaskBrowse:
    def test_no_auth(self, client):
        r = client.get("/task/browse")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.browse_tasks", return_value=[{"task_id": "t1", "title": "Fix"}])
    def test_success(self, mock_browse, mock_vk, client):
        r = client.get("/task/browse", headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.browse_tasks", return_value=[])
    def test_filter_by_skill(self, mock_browse, mock_vk, client):
        r = client.get("/task/browse?skill=python&status=open&limit=5", headers=AUTH)
        assert r.status_code == 200
        mock_browse.assert_called_once_with(status="open", skill="python", limit=5)


# ── POST /task/claim ───────────────────────────────────────────────────────

class TestTaskClaim:
    def test_no_auth(self, client):
        r = client.post("/task/claim", json={"task_id": "t1", "agent_id": "a"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_fields(self, mock_vk, client):
        r = client.post("/task/claim", headers=AUTH, json={"task_id": "t1"})
        assert r.status_code == 400

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.claim_task", return_value=True)
    def test_success(self, mock_claim, mock_vk, client):
        r = client.post("/task/claim", headers=AUTH,
                        json={"task_id": "t1", "agent_id": "agent-a"})
        assert r.status_code == 200
        assert r.get_json()["claimed"] is True


# ── POST /task/complete ────────────────────────────────────────────────────

class TestTaskComplete:
    def test_no_auth(self, client):
        r = client.post("/task/complete",
                        json={"task_id": "t1", "agent_id": "a", "result": "done"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_fields(self, mock_vk, client):
        r = client.post("/task/complete", headers=AUTH, json={"task_id": "t1"})
        assert r.status_code == 400

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.network.complete_task", return_value=True)
    @patch("routes.network.log_payment")
    def test_success(self, mock_log, mock_complete, mock_vk, client):
        r = client.post("/task/complete", headers=AUTH,
                        json={"task_id": "t1", "agent_id": "agent-a", "result": "fixed the bug"})
        assert r.status_code == 200
        assert r.get_json()["completed"] is True
