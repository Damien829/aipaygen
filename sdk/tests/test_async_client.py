"""Tests for the async AiPayGen SDK client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from aipaygen_sdk import AsyncClient, AuthError, PaymentRequired, RateLimitError


def _mock_response(status_code=200, json_data=None, headers=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.headers = headers or {}
    resp.text = json.dumps(json_data) if json_data else ""
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


@pytest.fixture
def async_client():
    return AsyncClient(api_key="apk_test_key", base_url="https://api.aipaygen.com")


class TestAsyncClientInit:
    def test_requires_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="API key required"):
                AsyncClient()

    def test_accepts_api_key(self):
        c = AsyncClient(api_key="apk_abc")
        assert repr(c) == "AsyncClient(base_url='https://api.aipaygen.com')"


class TestAsyncToolCalls:
    @pytest.mark.asyncio
    async def test_ask(self, async_client):
        mock_resp = _mock_response(json_data={"result": "Answer here"})
        with patch.object(async_client._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await async_client.ask("What is AI?")
            assert result.ok
            assert result.result == "Answer here"

    @pytest.mark.asyncio
    async def test_call_tool(self, async_client):
        mock_resp = _mock_response(json_data={"result": {"score": 0.9}})
        with patch.object(async_client._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await async_client.call_tool("sentiment", text="great")
            assert result.ok
            assert result.result["score"] == 0.9

    @pytest.mark.asyncio
    async def test_research(self, async_client):
        mock_resp = _mock_response(json_data={"result": "findings", "usage": {"tokens": 100}})
        with patch.object(async_client._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await async_client.research("topic")
            assert result.usage == {"tokens": 100}

    @pytest.mark.asyncio
    async def test_summarize(self, async_client):
        mock_resp = _mock_response(json_data={"result": "Short summary"})
        with patch.object(async_client._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await async_client.summarize("Long text goes here...")
            assert result.result == "Short summary"

    @pytest.mark.asyncio
    async def test_translate(self, async_client):
        mock_resp = _mock_response(json_data={"result": "Hola mundo"})
        with patch.object(async_client._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            result = await async_client.translate("Hello world", target="es")
            assert result.result == "Hola mundo"


class TestAsyncAuthErrors:
    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, async_client):
        mock_resp = _mock_response(status_code=401, json_data={"error": "Unauthorized"})
        with patch.object(async_client._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(AuthError):
                await async_client.ask("hello")


class TestAsyncPaymentRequired:
    @pytest.mark.asyncio
    async def test_402_raises_without_auto_pay(self, async_client):
        mock_resp = _mock_response(
            status_code=402,
            json_data={"payment": {"price": "0.01", "pay_to": "0x123", "network": "base"}},
            headers={},
        )
        with patch.object(async_client._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(PaymentRequired):
                await async_client.ask("hello")


class TestAsyncRateLimiting:
    @pytest.mark.asyncio
    async def test_429_retries_then_raises(self, async_client):
        mock_resp = _mock_response(
            status_code=429, json_data={}, headers={"Retry-After": "0.01"}
        )
        with patch.object(async_client._client, "request", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(RateLimitError):
                await async_client.ask("hello")

    @pytest.mark.asyncio
    async def test_429_recovers(self, async_client):
        rate_resp = _mock_response(status_code=429, json_data={}, headers={"Retry-After": "0.01"})
        ok_resp = _mock_response(json_data={"result": "ok"})
        with patch.object(
            async_client._client, "request",
            new_callable=AsyncMock,
            side_effect=[rate_resp, ok_resp],
        ):
            result = await async_client.ask("hello")
            assert result.ok


class TestAsyncContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        async with AsyncClient(api_key="apk_test") as c:
            mock_resp = _mock_response(json_data={"result": "ok"})
            with patch.object(c._client, "request", new_callable=AsyncMock, return_value=mock_resp):
                result = await c.ask("hello")
                assert result.ok
