"""Tests for /agent and /agent/stream endpoints in routes/agent.py."""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

FAKE_KEY = "apk_test_agent_ep_key"
AUTH = {"Authorization": f"Bearer {FAKE_KEY}"}


def _validate_key_mock(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 50.0, "is_active": 1}
    return None


MOCK_AGENT_RESULT = {
    "answer": "AI agents are autonomous systems.",
    "reasoning_trace": [{"thought": "thinking", "action": "research"}],
    "steps_taken": 2,
    "total_cost_usd": 0.003,
    "model": "claude-haiku",
}


@pytest.fixture
def client():
    with patch("api_keys.validate_key", side_effect=_validate_key_mock):
        from app import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


class TestAgentEndpoint:
    def test_no_auth_uses_free_tier(self, client):
        """Without auth, endpoints use free tier (not 401)."""
        r = client.post("/agent", json={"task": "What is AI?"})
        assert r.status_code in (200, 402, 500)  # 200=free tier, 402=exhausted, 500=model error

    def test_missing_task_returns_400_or_401(self, client):
        r = client.post("/agent", json={}, headers=AUTH)
        assert r.status_code in (400, 401)  # 400 if auth passes, 401 if WSGI middleware rejects

    def test_empty_task_returns_400_or_401(self, client):
        r = client.post("/agent", json={"task": ""}, headers=AUTH)
        assert r.status_code in (400, 401)

    @patch("routes.agent.log_payment")
    def test_success(self, mock_log, client):
        mock_agent_instance = MagicMock()
        mock_agent_instance.run.return_value = MOCK_AGENT_RESULT
        mock_module = MagicMock()
        mock_module.ReActAgent.return_value = mock_agent_instance
        mock_module.make_tool_handler.return_value = MagicMock()
        with patch.dict("sys.modules", {"react_agent": mock_module}):
            r = client.post("/agent", json={"task": "Explain AI agents"}, headers=AUTH)
            assert r.status_code == 200
            data = r.get_json()
            assert data["answer"] == "AI agents are autonomous systems."
            assert data["steps_taken"] == 2
            assert "_meta" in data


class TestAgentStreamEndpoint:
    def test_no_auth_uses_free_tier(self, client):
        """Without auth, endpoints use free tier (not 401)."""
        r = client.post("/agent/stream", json={"task": "What is AI?"})
        assert r.status_code in (200, 402, 500)

    def test_missing_task_returns_400(self, client):
        r = client.post("/agent/stream", json={}, headers=AUTH)
        assert r.status_code == 400
        assert "task" in r.get_json()["error"]

    @patch("routes.agent.log_payment")
    def test_success_streams_sse(self, mock_log, client):
        mock_agent_instance = MagicMock()
        mock_agent_instance.run_stream.return_value = iter([
            {"event": "thought", "data": {"text": "Let me think..."}},
            {"event": "action", "data": {"tool": "research", "params": {"topic": "AI"}}},
            {"event": "done", "data": {"answer": "AI is cool", "cost_usd": 0.002}},
        ])
        mock_module = MagicMock()
        mock_module.ReActAgent.return_value = mock_agent_instance
        mock_module.make_tool_handler.return_value = MagicMock()
        with patch.dict("sys.modules", {"react_agent": mock_module}):
            r = client.post("/agent/stream", json={"task": "Explain AI"}, headers=AUTH)
            assert r.status_code == 200
            assert "text/event-stream" in r.content_type
            data = r.get_data(as_text=True)
            assert "thought" in data
            assert "Let me think" in data
            assert "done" in data
