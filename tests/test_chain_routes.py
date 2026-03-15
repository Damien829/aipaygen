"""Tests for the /chain endpoint in routes/agent.py."""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

FAKE_KEY = "apk_test_chain_key"
AUTH = {"Authorization": f"Bearer {FAKE_KEY}"}


def _validate_key_mock(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 50.0, "is_active": 1}
    return None


def _mock_handler(params):
    """Generic mock handler that returns a dict with a result key."""
    return {"result": "mock output", "model": "claude-haiku"}


@pytest.fixture(scope="module")
def client():
    with patch("api_keys.validate_key", side_effect=_validate_key_mock):
        from app import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


class TestChainEndpoint:
    def test_no_auth_uses_free_tier(self, client):
        """Without auth, endpoints use free tier (not 401)."""
        r = client.post("/chain", json={"steps": [{"action": "research", "params": {"query": "AI"}}]})
        assert r.status_code in (200, 402, 500)

    def test_empty_steps_returns_400(self, client):
        r = client.post("/chain", json={"steps": []}, headers=AUTH)
        assert r.status_code == 400
        assert "steps" in r.get_json()["error"]

    def test_missing_steps_returns_400(self, client):
        r = client.post("/chain", json={}, headers=AUTH)
        assert r.status_code == 400

    def test_too_many_steps_returns_400(self, client):
        steps = [{"action": "research", "params": {"query": f"q{i}"}} for i in range(11)]
        r = client.post("/chain", json={"steps": steps}, headers=AUTH)
        assert r.status_code == 400
        assert "maximum 10" in r.get_json()["error"]

    def test_unknown_action_returns_400(self, client):
        r = client.post("/chain",
                        json={"steps": [{"action": "nonexistent_action", "params": {}}]},
                        headers=AUTH)
        assert r.status_code == 400
        assert "unknown action" in r.get_json()["error"]
        assert "available" in r.get_json()

    @patch("routes.agent._get_chain_handlers")
    @patch("routes.agent.log_payment")
    def test_single_step_success(self, mock_log, mock_handlers, client):
        mock_handlers.return_value = {"research": _mock_handler}
        r = client.post("/chain",
                        json={"steps": [{"action": "research", "params": {"query": "AI"}}]},
                        headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["steps_completed"] == 1
        assert len(data["chain"]) == 1
        assert data["chain"][0]["tool"] == "research"
        assert data["final_result"] is not None

    @patch("routes.agent._get_chain_handlers")
    @patch("routes.agent.log_payment")
    def test_multi_step_chain(self, mock_log, mock_handlers, client):
        mock_handlers.return_value = {
            "research": lambda p: {"result": "research output"},
            "summarize": lambda p: {"summary": "summary output"},
        }
        r = client.post("/chain", json={"steps": [
            {"action": "research", "params": {"query": "AI"}},
            {"action": "summarize", "params": {"text": "{{prev_result}}"}},
        ]}, headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["steps_completed"] == 2
        assert len(data["chain"]) == 2

    @patch("routes.agent._get_chain_handlers")
    @patch("routes.agent.log_payment")
    def test_prev_result_substitution(self, mock_log, mock_handlers, client):
        captured_params = {}

        def capture_summarize(params):
            captured_params.update(params)
            return {"summary": "done"}

        mock_handlers.return_value = {
            "research": lambda p: {"result": "FIRST_STEP_OUTPUT"},
            "summarize": capture_summarize,
        }
        r = client.post("/chain", json={"steps": [
            {"action": "research", "params": {"query": "AI"}},
            {"action": "summarize", "params": {"text": "{{prev_result}}"}},
        ]}, headers=AUTH)
        assert r.status_code == 200
        assert "FIRST_STEP_OUTPUT" in captured_params.get("text", "")

    @patch("routes.agent._get_chain_handlers")
    @patch("routes.agent.log_payment")
    def test_modern_tool_input_format(self, mock_log, mock_handlers, client):
        """Modern format uses 'tool' and 'input' instead of 'action' and 'params'."""
        mock_handlers.return_value = {"research": _mock_handler}
        r = client.post("/chain",
                        json={"steps": [{"tool": "research", "input": {"query": "AI"}}]},
                        headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["steps_completed"] == 1
        assert data["chain"][0]["tool"] == "research"

    @patch("routes.agent._get_chain_handlers")
    @patch("routes.agent.log_payment")
    def test_dollar_prev_result_substitution(self, mock_log, mock_handlers, client):
        """$prev.result syntax resolves to previous step output."""
        captured = {}

        def capture_translate(params):
            captured.update(params)
            return {"result": "translated"}

        mock_handlers.return_value = {
            "summarize": lambda p: {"result": "SUMMARY_OUTPUT"},
            "translate": capture_translate,
        }
        r = client.post("/chain", json={"steps": [
            {"tool": "summarize", "input": {"text": "some long text"}},
            {"tool": "translate", "input": {"text": "$prev.result", "target": "es"}},
        ]}, headers=AUTH)
        assert r.status_code == 200
        assert "SUMMARY_OUTPUT" in captured.get("text", "")

    @patch("routes.agent._get_chain_handlers")
    @patch("routes.agent.log_payment")
    def test_chain_returns_timing(self, mock_log, mock_handlers, client):
        """Chain response includes per-step and total timing."""
        mock_handlers.return_value = {"research": _mock_handler}
        # Clear rate limit caches to avoid 429
        from helpers import _endpoint_rate, _ip_rate
        _endpoint_rate.clear()
        _ip_rate.clear()
        r = client.post("/chain",
                        json={"steps": [{"tool": "research", "input": {"query": "AI"}}]},
                        headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert "total_time_ms" in data
        assert "time_ms" in data["chain"][0]
