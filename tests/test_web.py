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
    import app as app_module
    with app_module.app.test_request_context(
        headers={"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"}
    ):
        assert app_module._get_client_ip() == "1.2.3.4"


def test_get_client_ip_falls_back_to_remote_addr():
    import app as app_module
    with app_module.app.test_request_context():
        assert app_module._get_client_ip() == "unknown"


def test_get_client_ip_comma_separated():
    import app as app_module
    with app_module.app.test_request_context(
        headers={"CF-Connecting-IP": "1.2.3.4, 5.6.7.8"}
    ):
        assert app_module._get_client_ip() == "1.2.3.4"


def test_discover_returns_json_for_agents():
    import app as app_module
    client = app_module.app.test_client()
    resp = client.get("/discover", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "meta" in data
    assert "payment" in data
    assert "categories" in data
    assert "links" in data
    assert data["meta"]["name"] == "AiPayGen"
    assert len(data["categories"]) > 0
    assert isinstance(data["categories"], dict)


def test_discover_returns_html_for_browsers():
    import app as app_module
    client = app_module.app.test_client()
    resp = client.get("/discover", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert b"AiPayGen" in resp.data
    assert b"<!DOCTYPE html>" in resp.data
