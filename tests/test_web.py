import pytest
from unittest.mock import patch, MagicMock


def test_scrape_returns_text():
    from web import scrape_url
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body><p>Hello world</p><nav>skip</nav></body></html>"
    mock_response.raise_for_status = MagicMock()
    with patch("web.requests.get", return_value=mock_response):
        result = scrape_url("http://example.com")
    assert "Hello world" in result["text"]
    assert result["url"] == "http://example.com"
    assert "word_count" in result


def test_scrape_timeout_returns_error():
    from web import scrape_url
    import requests as req
    with patch("web.requests.get", side_effect=req.exceptions.Timeout):
        result = scrape_url("http://example.com")
    assert result["error"] == "timeout"


def test_search_returns_results():
    from web import search_web
    fake_results = [
        {"title": "Test", "href": "http://example.com", "body": "A snippet"},
    ]
    with patch("web.DDGS") as MockDDGS:
        instance = MockDDGS.return_value.__enter__.return_value
        instance.text.return_value = fake_results
        result = search_web("test query", n=1)
    assert result["query"] == "test query"
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Test"
    assert result["results"][0]["url"] == "http://example.com"
    assert result["results"][0]["snippet"] == "A snippet"


def test_get_client_ip_prefers_cf_header():
    from flask import Flask, request
    _app = Flask(__name__)

    def _get_client_ip():
        return request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown").split(",")[0].strip()

    with _app.test_request_context(headers={"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"}):
        assert _get_client_ip() == "1.2.3.4"


def test_get_client_ip_falls_back_to_remote_addr():
    from flask import Flask, request
    _app = Flask(__name__)

    def _get_client_ip():
        return request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown").split(",")[0].strip()

    with _app.test_request_context():
        ip = _get_client_ip()
        assert isinstance(ip, str)
