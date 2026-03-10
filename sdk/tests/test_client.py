"""Tests for the synchronous AiPayGen SDK client."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from aipaygen_sdk import Client, AuthError, PaymentRequired, RateLimitError, ToolResult


@pytest.fixture
def client():
    return Client(api_key="apk_test_key", base_url="https://api.aipaygen.com")


def _mock_response(status_code=200, json_data=None, headers=None, text=""):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.headers = headers or {}
    resp.text = text
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


class TestClientInit:
    def test_requires_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="API key required"):
                Client()

    def test_accepts_api_key(self):
        c = Client(api_key="apk_abc")
        assert repr(c) == "Client(base_url='https://api.aipaygen.com')"

    def test_env_api_key(self):
        with patch.dict("os.environ", {"AIPAYGEN_API_KEY": "apk_env"}):
            c = Client()
            assert c._api_key == "apk_env"

    def test_custom_base_url(self):
        c = Client(api_key="apk_x", base_url="https://custom.api.com/")
        assert c._base_url == "https://custom.api.com"


class TestToolCalls:
    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_ask(self, mock_req, client):
        mock_req.return_value = _mock_response(
            json_data={"result": "Quantum computing uses qubits."}
        )
        result = client.ask("What is quantum computing?")
        assert result.ok
        assert result.result == "Quantum computing uses qubits."

    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_call_tool(self, mock_req, client):
        mock_req.return_value = _mock_response(
            json_data={"result": {"sentiment": "positive", "score": 0.95}}
        )
        result = client.call_tool("sentiment", text="I love it")
        assert result.ok
        assert result.result["sentiment"] == "positive"
        # Verify correct URL
        call_args = mock_req.call_args
        assert "tools/sentiment" in call_args[0][1]

    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_research(self, mock_req, client):
        mock_req.return_value = _mock_response(
            json_data={"result": "Research findings...", "usage": {"tokens": 150}}
        )
        result = client.research("AI frameworks")
        assert result.ok
        assert result.usage == {"tokens": 150}

    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_code(self, mock_req, client):
        mock_req.return_value = _mock_response(
            json_data={"result": "def fib(n): ..."}
        )
        result = client.code("fibonacci", language="python")
        assert result.ok

    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_error_response(self, mock_req, client):
        mock_req.return_value = _mock_response(
            json_data={"result": None, "error": "Tool not found"}
        )
        result = client.call_tool("nonexistent")
        assert result.error == "Tool not found"
        assert not result.ok


class TestAuthErrors:
    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_401_raises_auth_error(self, mock_req, client):
        mock_req.return_value = _mock_response(
            status_code=401, json_data={"error": "Invalid API key"}
        )
        with pytest.raises(AuthError):
            client.ask("hello")

    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_403_raises_auth_error(self, mock_req, client):
        mock_req.return_value = _mock_response(
            status_code=403, json_data={"error": "Forbidden"}
        )
        with pytest.raises(AuthError):
            client.ask("hello")


class TestPaymentRequired:
    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_402_raises_without_auto_pay(self, mock_req, client):
        mock_req.return_value = _mock_response(
            status_code=402,
            json_data={"error": "Payment required"},
            headers={
                "x-payment-price": "0.01",
                "x-payment-pay-to": "0x123",
                "x-payment-network": "eip155:8453",
            },
        )
        with pytest.raises(PaymentRequired) as exc_info:
            client.ask("hello")
        assert exc_info.value.payment_info["price"] == "0.01"

    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_402_auto_pay_no_wallet_raises(self, mock_req):
        c = Client(api_key="apk_x", auto_pay=True)
        mock_req.return_value = _mock_response(
            status_code=402,
            json_data={},
            headers={"x-payment-price": "0.01", "x-payment-pay-to": "0x123", "x-payment-network": "base"},
        )
        with pytest.raises(PaymentRequired, match="wallet_key"):
            c.ask("hello")

    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_402_extracts_payment_from_body(self, mock_req, client):
        mock_req.return_value = _mock_response(
            status_code=402,
            json_data={"payment": {"price": "0.05", "pay_to": "0xABC", "network": "base"}},
            headers={},
        )
        with pytest.raises(PaymentRequired) as exc_info:
            client.ask("hello")
        assert exc_info.value.payment_info["pay_to"] == "0xABC"


class TestRateLimiting:
    @patch("aipaygen_sdk.client.requests.Session.request")
    @patch("aipaygen_sdk.client.time.sleep")
    def test_429_retries_then_raises(self, mock_sleep, mock_req, client):
        mock_req.return_value = _mock_response(
            status_code=429,
            json_data={"error": "Rate limited"},
            headers={"Retry-After": "1"},
        )
        with pytest.raises(RateLimitError) as exc_info:
            client.ask("hello")
        assert exc_info.value.retry_after == 1.0
        # Should have retried max_retries times
        assert mock_sleep.call_count == client._max_retries

    @patch("aipaygen_sdk.client.requests.Session.request")
    @patch("aipaygen_sdk.client.time.sleep")
    def test_429_recovers_on_retry(self, mock_sleep, mock_req, client):
        rate_limit_resp = _mock_response(
            status_code=429, json_data={}, headers={"Retry-After": "1"}
        )
        success_resp = _mock_response(
            json_data={"result": "success"}
        )
        mock_req.side_effect = [rate_limit_resp, success_resp]
        result = client.ask("hello")
        assert result.ok
        assert result.result == "success"


class TestStreaming:
    @patch("aipaygen_sdk.client.requests.Session.post")
    def test_stream(self, mock_post, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.iter_lines.return_value = [
            "data: chunk1",
            "data: chunk2",
            "data: [DONE]",
        ]
        mock_post.return_value = mock_resp

        chunks = list(client.stream("research", query="test"))
        assert len(chunks) == 3
        assert chunks[0].data == "chunk1"
        assert chunks[1].data == "chunk2"
        assert chunks[2].done is True


class TestContextManager:
    @patch("aipaygen_sdk.client.requests.Session.request")
    def test_context_manager(self, mock_req):
        mock_req.return_value = _mock_response(json_data={"result": "ok"})
        with Client(api_key="apk_test") as c:
            result = c.ask("hello")
            assert result.ok


class TestToolResult:
    def test_ok_property(self):
        r = ToolResult(result="data", status_code=200)
        assert r.ok

    def test_not_ok_with_error(self):
        r = ToolResult(error="bad", status_code=200)
        assert not r.ok

    def test_not_ok_with_status(self):
        r = ToolResult(result="x", status_code=500)
        assert not r.ok

    def test_str_representation(self):
        r = ToolResult(result="hello")
        assert "hello" in str(r)
        r2 = ToolResult(error="fail")
        assert "fail" in str(r2)
