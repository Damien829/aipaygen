"""Flask route tests using test_client — covers critical endpoints."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] in ("ok", "healthy")


def test_models_list(client):
    r = client.get("/models")
    assert r.status_code == 200
    data = r.get_json()
    assert "models" in data
    assert len(data["models"]) >= 10


def test_models_feedback(client):
    r = client.post("/models/feedback", json={
        "model": "claude-haiku",
        "domain": "code",
        "quality_score": 0.85,
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "recorded"


def test_models_feedback_missing_model(client):
    r = client.post("/models/feedback", json={"domain": "code"})
    assert r.status_code == 400


def test_models_outcomes(client):
    r = client.get("/models/outcomes")
    assert r.status_code == 200
    data = r.get_json()
    assert "outcomes" in data


def test_research_requires_topic(client):
    r = client.post("/research", json={})
    # May return 400 (missing topic) or 402 (x402 payment required first)
    assert r.status_code in (400, 402)


def test_stream_research_requires_topic(client):
    r = client.post("/stream/research", json={})
    assert r.status_code == 400


def test_stream_write_requires_prompt(client):
    r = client.post("/stream/write", json={})
    assert r.status_code == 400


def test_stream_analyze_requires_content(client):
    r = client.post("/stream/analyze", json={})
    assert r.status_code == 400


def test_agent_requires_task(client):
    r = client.post("/agent", json={})
    assert r.status_code == 400


@patch("routes.ai_tools.scrape_url")
@patch("routes.ai_tools.search_web")
@patch("routes.ai_tools.call_model")
def test_research_with_mock(mock_call, mock_search, mock_scrape, client):
    mock_search.return_value = {
        "results": [
            {"title": "Test Result", "url": "https://example.com", "snippet": "A test result"},
        ]
    }
    mock_scrape.return_value = {
        "url": "https://example.com",
        "text": "This is test content about the topic with enough words to pass the filter threshold for research.",
        "word_count": 100,
    }
    mock_call.return_value = {
        "text": "Test research answer with [1] citation.",
        "model": "claude-haiku",
        "model_id": "claude-haiku-4-5-20251001",
        "provider": "anthropic",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": 0.001,
        "selected_reason": None,
    }
    r = client.post("/research", json={"question": "test topic"})
    assert r.status_code == 200
    data = r.get_json()
    assert "answer" in data
    assert "sources" in data
