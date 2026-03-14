"""Tests for routes/streaming.py — /stream/research, /stream/write, /stream/analyze."""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

FAKE_KEY = "apk_test_stream_key"
AUTH = {"Authorization": f"Bearer {FAKE_KEY}"}


def _validate_key_mock(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 50.0, "is_active": 1}
    return None


def _mock_stream_chunks():
    """Simulate call_model_stream yielding text chunks then a done marker."""
    yield {"text": "chunk1"}
    yield {"text": "chunk2"}
    yield {"done": True, "model": "claude-haiku", "cost_usd": 0.01}


@pytest.fixture
def client():
    with patch("api_keys.validate_key", side_effect=_validate_key_mock):
        from app import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


# ── /stream/research ──────────────────────────────────────────────────────

class TestStreamResearch:
    @patch("routes.streaming.call_model_stream", side_effect=lambda *a, **kw: _mock_stream_chunks())
    def test_no_auth_uses_free_tier(self, mock_stream, client):
        """Without auth, endpoints use free tier (not 401)."""
        r = client.post("/stream/research", json={"topic": "AI"})
        assert r.status_code in (200, 402)

    def test_missing_topic_returns_400(self, client):
        r = client.post("/stream/research", json={}, headers=AUTH)
        assert r.status_code == 400
        assert "topic" in r.get_json()["error"]

    def test_empty_topic_returns_400(self, client):
        r = client.post("/stream/research", json={"topic": ""}, headers=AUTH)
        assert r.status_code == 400

    @patch("routes.streaming.log_payment")
    @patch("routes.streaming.call_model_stream", side_effect=lambda *a, **kw: _mock_stream_chunks())
    def test_success_streams_sse(self, mock_stream, mock_log, client):
        r = client.post("/stream/research", json={"topic": "quantum computing"}, headers=AUTH)
        assert r.status_code == 200
        assert "text/event-stream" in r.content_type
        data = r.get_data(as_text=True)
        assert "chunk1" in data
        assert "chunk2" in data
        assert '"done": true' in data


# ── /stream/write ─────────────────────────────────────────────────────────

class TestStreamWrite:
    @patch("routes.streaming.call_model_stream", side_effect=lambda *a, **kw: _mock_stream_chunks())
    def test_no_auth_uses_free_tier(self, mock_stream, client):
        """Without auth, endpoints use free tier (not 401)."""
        r = client.post("/stream/write", json={"prompt": "hello"})
        assert r.status_code in (200, 402)

    def test_missing_prompt_returns_400(self, client):
        r = client.post("/stream/write", json={}, headers=AUTH)
        assert r.status_code == 400
        assert "prompt" in r.get_json()["error"]

    @patch("routes.streaming.log_payment")
    @patch("routes.streaming.call_model_stream", side_effect=lambda *a, **kw: _mock_stream_chunks())
    def test_success_streams_sse(self, mock_stream, mock_log, client):
        r = client.post("/stream/write", json={"prompt": "Write a poem", "style": "casual"}, headers=AUTH)
        assert r.status_code == 200
        assert "text/event-stream" in r.content_type
        data = r.get_data(as_text=True)
        assert "chunk1" in data
        assert '"done": true' in data


# ── /stream/analyze ───────────────────────────────────────────────────────

class TestStreamAnalyze:
    @patch("routes.streaming.call_model_stream", side_effect=lambda *a, **kw: _mock_stream_chunks())
    def test_no_auth_uses_free_tier(self, mock_stream, client):
        """Without auth, endpoints use free tier (not 401)."""
        r = client.post("/stream/analyze", json={"content": "text"})
        assert r.status_code in (200, 402)

    def test_missing_content_returns_400(self, client):
        r = client.post("/stream/analyze", json={}, headers=AUTH)
        assert r.status_code == 400
        assert "content" in r.get_json()["error"]

    @patch("routes.streaming.log_payment")
    @patch("routes.streaming.call_model_stream", side_effect=lambda *a, **kw: _mock_stream_chunks())
    def test_success_streams_sse(self, mock_stream, mock_log, client):
        r = client.post("/stream/analyze",
                        json={"content": "The market rose 5% yesterday"},
                        headers=AUTH)
        assert r.status_code == 200
        assert "text/event-stream" in r.content_type
        data = r.get_data(as_text=True)
        assert "chunk2" in data
        assert '"done": true' in data
