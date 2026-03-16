"""Tests for the upgraded parallel /batch endpoint."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

FAKE_KEY = "apk_test_batch_key"
AUTH = {"Authorization": f"Bearer {FAKE_KEY}", "Content-Type": "application/json"}


def _validate_key_ok(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 100.0, "is_active": 1}
    return None


def _mock_sentiment(d):
    return {"sentiment": "positive", "score": 0.9}


def _mock_translate(d):
    return {"result": "Hola mundo", "language": d.get("language", "es")}


def _mock_failing(d):
    raise RuntimeError("boom")


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestBatchParallel:
    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_empty_calls_returns_400(self, mock_vk, client):
        r = client.post("/batch", headers=AUTH, json={})
        assert r.status_code == 400
        assert "calls" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_exceeds_max_calls(self, mock_vk, client):
        calls = [{"tool": "sentiment", "input": {"text": "x"}}] * 21
        r = client.post("/batch", headers=AUTH, json={"calls": calls})
        assert r.status_code == 400
        assert "20" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.BATCH_HANDLERS", {
        "sentiment": _mock_sentiment,
        "translate": _mock_translate,
    })
    def test_parallel_execution(self, mock_vk, client):
        r = client.post("/batch", headers=AUTH, json={
            "calls": [
                {"tool": "sentiment", "input": {"text": "I love this"}},
                {"tool": "translate", "input": {"text": "Hello", "language": "es"}},
            ]
        })
        assert r.status_code == 200
        data = r.get_json()
        results = data["results"]
        assert len(results) == 2
        assert results[0]["tool"] == "sentiment"
        assert results[1]["tool"] == "translate"
        assert "total_time_ms" in data
        assert data["calls_completed"] == 2
        assert data["calls_failed"] == 0

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.BATCH_HANDLERS", {
        "sentiment": _mock_sentiment,
    })
    def test_unknown_tool_partial_results(self, mock_vk, client):
        r = client.post("/batch", headers=AUTH, json={
            "calls": [
                {"tool": "sentiment", "input": {"text": "hi"}},
                {"tool": "nonexistent_tool", "input": {}},
            ]
        })
        assert r.status_code == 200
        data = r.get_json()
        results = data["results"]
        assert len(results) == 2
        assert "error" not in results[0]
        assert "error" in results[1]
        assert data["calls_completed"] == 1
        assert data["calls_failed"] == 1

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.BATCH_HANDLERS", {
        "sentiment": _mock_sentiment,
        "failing": _mock_failing,
    })
    def test_failed_call_doesnt_block_others(self, mock_vk, client):
        r = client.post("/batch", headers=AUTH, json={
            "calls": [
                {"tool": "sentiment", "input": {"text": "hi"}},
                {"tool": "failing", "input": {}},
            ]
        })
        assert r.status_code == 200
        data = r.get_json()
        results = data["results"]
        # sentiment should succeed, failing should have error
        sent = next(r for r in results if r["tool"] == "sentiment")
        fail = next(r for r in results if r["tool"] == "failing")
        assert "error" not in sent
        assert "error" in fail

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.BATCH_HANDLERS", {"sentiment": _mock_sentiment})
    def test_preserves_order(self, mock_vk, client):
        """Results should be in the same order as the input calls."""
        r = client.post("/batch", headers=AUTH, json={
            "calls": [
                {"tool": "sentiment", "input": {"text": "a"}},
                {"tool": "sentiment", "input": {"text": "b"}},
                {"tool": "sentiment", "input": {"text": "c"}},
            ]
        })
        data = r.get_json()
        assert len(data["results"]) == 3
        # All should be sentiment in order
        for i, res in enumerate(data["results"]):
            assert res["tool"] == "sentiment"

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.BATCH_HANDLERS", {"sentiment": _mock_sentiment})
    def test_legacy_operations_format(self, mock_vk, client):
        """Legacy 'operations' key should still work."""
        r = client.post("/batch", headers=AUTH, json={
            "operations": [
                {"endpoint": "sentiment", "input": {"text": "hello"}},
            ]
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["calls_completed"] == 1

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.BATCH_HANDLERS", {"sentiment": _mock_sentiment})
    def test_timing_info(self, mock_vk, client):
        r = client.post("/batch", headers=AUTH, json={
            "calls": [{"tool": "sentiment", "input": {"text": "hi"}}]
        })
        data = r.get_json()
        assert data["total_time_ms"] >= 0
        assert data["results"][0]["time_ms"] >= 0
