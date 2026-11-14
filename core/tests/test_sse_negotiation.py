"""Tests for SSE content negotiation on /research and /write endpoints."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

FAKE_KEY = "apk_test_sse_key"
AUTH = {"Authorization": f"Bearer {FAKE_KEY}", "Content-Type": "application/json"}
SSE_HEADERS = {**AUTH, "Accept": "text/event-stream"}


def _validate_key_ok(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 100.0, "is_active": 1}
    return None


def _mock_stream_chunks(*a, **kw):
    yield {"text": "chunk1"}
    yield {"text": "chunk2"}
    yield {"done": True, "model": "claude-haiku", "cost_usd": 0.01}


def _mock_search_web(q, n=5):
    return {"results": [
        {"title": "Source 1", "url": "https://example.com/1"},
        {"title": "Source 2", "url": "https://example.com/2"},
        {"title": "Source 3", "url": "https://example.com/3"},
    ]}


def _mock_scrape_url(url, timeout=8):
    return {"url": url, "text": "Some content " * 20, "word_count": 100}


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestResearchSSE:
    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.call_model_stream", side_effect=_mock_stream_chunks)
    @patch("routes.ai_tools.scrape_url", side_effect=_mock_scrape_url)
    @patch("routes.ai_tools.search_web", side_effect=_mock_search_web)
    def test_sse_returns_event_stream(self, mock_search, mock_scrape, mock_stream, mock_vk, client):
        r = client.post("/research", headers=SSE_HEADERS, json={"question": "What is AI?"})
        assert r.status_code == 200
        assert "text/event-stream" in r.content_type
        data = r.get_data(as_text=True)
        assert "chunk1" in data
        assert "chunk2" in data
        assert '"done": true' in data

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.call_model_stream", side_effect=_mock_stream_chunks)
    @patch("routes.ai_tools.scrape_url", side_effect=_mock_scrape_url)
    @patch("routes.ai_tools.search_web", side_effect=_mock_search_web)
    def test_sse_includes_sources_first(self, mock_search, mock_scrape, mock_stream, mock_vk, client):
        r = client.post("/research", headers=SSE_HEADERS, json={"question": "What is AI?"})
        data = r.get_data(as_text=True)
        lines = [l for l in data.split("\n") if l.startswith("data:")]
        # First event should contain sources
        first = json.loads(lines[0].replace("data: ", ""))
        assert "sources" in first

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_no_sse_header_returns_json(self, mock_vk, client):
        """Without Accept: text/event-stream, should return normal JSON."""
        with patch("routes.ai_tools.search_web", side_effect=_mock_search_web), \
             patch("routes.ai_tools.scrape_url", side_effect=_mock_scrape_url), \
             patch("routes.ai_tools.call_llm") as mock_llm:
            mock_llm.return_value = ({"text": "AI is...", "model": "haiku"}, None)
            r = client.post("/research", headers=AUTH, json={"question": "What is AI?"})
            assert r.status_code == 200
            assert "application/json" in r.content_type


class TestWriteSSE:
    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.call_model_stream", side_effect=_mock_stream_chunks)
    def test_sse_returns_event_stream(self, mock_stream, mock_vk, client):
        r = client.post("/write", headers=SSE_HEADERS, json={"spec": "Write a haiku"})
        assert r.status_code == 200
        assert "text/event-stream" in r.content_type
        data = r.get_data(as_text=True)
        assert "chunk1" in data
        assert '"done": true' in data

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.ai_tools.call_model_stream", side_effect=_mock_stream_chunks)
    def test_sse_done_includes_type(self, mock_stream, mock_vk, client):
        r = client.post("/write", headers=SSE_HEADERS,
                        json={"spec": "Write a poem", "type": "poem"})
        data = r.get_data(as_text=True)
        lines = [l for l in data.split("\n") if l.startswith("data:") and "done" in l]
        done_event = json.loads(lines[0].replace("data: ", ""))
        assert done_event["type"] == "poem"

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_no_sse_header_returns_json(self, mock_vk, client):
        with patch("routes.ai_tools.call_llm") as mock_llm:
            mock_llm.return_value = ({"text": "A poem...", "model": "haiku"}, None)
            r = client.post("/write", headers=AUTH, json={"spec": "Write a poem"})
            assert r.status_code == 200
            assert "application/json" in r.content_type
