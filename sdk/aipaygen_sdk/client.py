"""Synchronous client for AiPayGen API."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterator, Optional

import requests

from .auth import build_auth_headers, resolve_api_key
from .exceptions import (
    AiPayGenError,
    AuthError,
    PaymentRequired,
    RateLimitError,
    ServerError,
)
from .types import PaymentReceipt, StreamChunk, ToolResult, X402PaymentInfo

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.aipaygen.com"


class Client:
    """Synchronous AiPayGen API client with auto-402 handling.

    Usage::

        from aipaygen_sdk import Client

        client = Client(api_key="apk_xxx")
        result = client.ask("What is quantum computing?")
        print(result.result)

    Auto-pay mode (pays USDC on 402)::

        client = Client(api_key="apk_xxx", auto_pay=True, wallet_key="0x...")
        result = client.research("AI frameworks 2026")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = _DEFAULT_BASE_URL,
        auto_pay: bool = False,
        wallet_key: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        self._api_key = resolve_api_key(api_key)
        self._base_url = base_url.rstrip("/")
        self._auto_pay = auto_pay
        self._wallet_key = wallet_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(build_auth_headers(self._api_key))

    # ── Convenience methods ──────────────────────────────────────────

    def ask(self, prompt: str, **kwargs: Any) -> ToolResult:
        """Ask a question."""
        return self.call_tool("ask", prompt=prompt, **kwargs)

    def research(self, query: str, **kwargs: Any) -> ToolResult:
        """Research a topic."""
        return self.call_tool("research", query=query, **kwargs)

    def code(self, prompt: str, language: str = "python", **kwargs: Any) -> ToolResult:
        """Generate code."""
        return self.call_tool("code", prompt=prompt, language=language, **kwargs)

    def summarize(self, text: str, **kwargs: Any) -> ToolResult:
        """Summarize text."""
        return self.call_tool("summarize", text=text, **kwargs)

    def translate(self, text: str, target: str = "en", **kwargs: Any) -> ToolResult:
        """Translate text."""
        return self.call_tool("translate", text=text, target=target, **kwargs)

    def sentiment(self, text: str, **kwargs: Any) -> ToolResult:
        """Analyze sentiment."""
        return self.call_tool("sentiment", text=text, **kwargs)

    def extract(self, text: str, **kwargs: Any) -> ToolResult:
        """Extract structured data from text."""
        return self.call_tool("extract", text=text, **kwargs)

    def classify(self, text: str, categories: list = None, **kwargs: Any) -> ToolResult:
        """Classify text."""
        return self.call_tool("classify", text=text, categories=categories or [], **kwargs)

    # ── Core methods ─────────────────────────────────────────────────

    def call_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Call any AiPayGen tool by name.

        Args:
            tool_name: Tool name (e.g., "ask", "sentiment", "research").
            **kwargs: Tool parameters.

        Returns:
            ToolResult with the response data.

        Raises:
            AuthError: On 401/403.
            PaymentRequired: On 402 when auto_pay is off.
            RateLimitError: On 429 after exhausting retries.
            ServerError: On 5xx errors.
        """
        url = f"{self._base_url}/tools/{tool_name}"
        return self._request("POST", url, json=kwargs)

    def stream(self, tool_name: str, **kwargs: Any) -> Iterator[StreamChunk]:
        """Stream results from a tool call via SSE.

        Args:
            tool_name: Tool name.
            **kwargs: Tool parameters.

        Yields:
            StreamChunk objects as data arrives.
        """
        url = f"{self._base_url}/tools/{tool_name}/stream"
        headers = dict(self._session.headers)
        headers["Accept"] = "text/event-stream"

        resp = self._session.post(
            url, json=kwargs, headers=headers, stream=True, timeout=self._timeout
        )
        if not resp.ok:
            if resp.status_code in (401, 403):
                raise AuthError(response=self._safe_json(resp))
            if resp.status_code == 429:
                raise RateLimitError(response=self._safe_json(resp))
            if resp.status_code >= 500:
                raise ServerError(status_code=resp.status_code, response=self._safe_json(resp))

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    yield StreamChunk(data="", done=True)
                    return
                yield StreamChunk(data=data)
            elif line.startswith("event: "):
                yield StreamChunk(data="", event=line[7:])

    def check_balance(self) -> Dict[str, Any]:
        """Check API key balance and usage."""
        url = f"{self._base_url}/auth/balance"
        resp = self._session.get(url, timeout=self._timeout)
        self._check_status(resp)
        return resp.json()

    def list_tools(self) -> Dict[str, Any]:
        """List available tools."""
        url = f"{self._base_url}/tools"
        resp = self._session.get(url, timeout=self._timeout)
        self._check_status(resp)
        return resp.json()

    # ── Internal ─────────────────────────────────────────────────────

    def _request(self, method: str, url: str, **kwargs: Any) -> ToolResult:
        """Make a request with retry and 402 handling."""
        kwargs.setdefault("timeout", self._timeout)
        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = self._session.request(method, url, **kwargs)
            except requests.RequestException as e:
                last_error = e
                if attempt < self._max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise AiPayGenError(f"Request failed: {e}") from e

            # Success
            if resp.ok:
                return self._parse_response(resp)

            # Auth error
            if resp.status_code in (401, 403):
                raise AuthError(response=self._safe_json(resp))

            # Payment required
            if resp.status_code == 402:
                return self._handle_402(resp, method, url, kwargs)

            # Rate limit
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                if attempt < self._max_retries:
                    logger.info("Rate limited, retrying in %.1fs", retry_after)
                    time.sleep(min(retry_after, 30))
                    continue
                raise RateLimitError(retry_after=retry_after, response=self._safe_json(resp))

            # Server error
            if resp.status_code >= 500:
                if attempt < self._max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ServerError(
                    status_code=resp.status_code, response=self._safe_json(resp)
                )

            # Other errors
            raise AiPayGenError(
                f"HTTP {resp.status_code}", status_code=resp.status_code,
                response=self._safe_json(resp),
            )

        raise AiPayGenError(f"Request failed after {self._max_retries} retries: {last_error}")

    def _handle_402(self, resp: requests.Response, method: str, url: str, kwargs: dict) -> ToolResult:
        """Handle 402 Payment Required response."""
        payment_info = self._extract_payment_info(resp)

        if not self._auto_pay or not self._wallet_key:
            raise PaymentRequired(
                message="Payment required. Enable auto_pay and provide wallet_key to pay automatically.",
                payment_info=payment_info.__dict__ if payment_info else {},
                response=self._safe_json(resp),
            )

        # Auto-pay: sign and retry
        logger.info("402 received, auto-paying $%s USDC to %s", payment_info.price, payment_info.pay_to)

        try:
            payment_header = self._sign_payment(payment_info)
        except Exception as e:
            raise PaymentRequired(
                message=f"Payment signing failed: {e}",
                payment_info=payment_info.__dict__,
            ) from e

        # Retry with payment header
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"]["X-Payment"] = payment_header

        retry_resp = self._session.request(method, url, **kwargs)

        if retry_resp.ok:
            result = self._parse_response(retry_resp)
            result.paid = True
            result.receipt = PaymentReceipt(
                endpoint=url,
                amount_usdc=payment_info.price,
                pay_to=payment_info.pay_to,
                network=payment_info.network,
                tx_hash=retry_resp.headers.get("x-payment-receipt"),
                success=True,
            )
            return result

        raise PaymentRequired(
            message=f"Payment accepted but request failed: HTTP {retry_resp.status_code}",
            response=self._safe_json(retry_resp),
        )

    def _sign_payment(self, info: X402PaymentInfo) -> str:
        """Sign an x402 payment. Requires eth-account."""
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
        except ImportError:
            raise ImportError(
                "eth-account required for auto-pay. Install with: "
                "pip install aipaygen-sdk[crypto]"
            )

        message = f"x402:pay:{info.pay_to}:{info.price}:{info.network}"
        msg = encode_defunct(text=message)
        signed = Account.sign_message(msg, private_key=self._wallet_key)
        return signed.signature.hex()

    @staticmethod
    def _extract_payment_info(resp: requests.Response) -> X402PaymentInfo:
        """Extract x402 payment info from 402 response headers/body."""
        headers = resp.headers
        info = X402PaymentInfo(
            price=headers.get("x-payment-price", "0"),
            pay_to=headers.get("x-payment-pay-to", ""),
            network=headers.get("x-payment-network", ""),
            token=headers.get("x-payment-token", "USDC"),
            description=headers.get("x-payment-description", ""),
        )

        # Also check JSON body for payment details
        try:
            body = resp.json()
            if "payment" in body:
                p = body["payment"]
                info.price = info.price or p.get("price", "0")
                info.pay_to = info.pay_to or p.get("pay_to", "")
                info.network = info.network or p.get("network", "")
        except Exception:
            pass

        return info

    @staticmethod
    def _parse_response(resp: requests.Response) -> ToolResult:
        """Parse a successful response into ToolResult."""
        try:
            data = resp.json()
        except Exception:
            return ToolResult(result=resp.text, status_code=resp.status_code)

        return ToolResult(
            result=data.get("result", data),
            error=data.get("error"),
            usage=data.get("usage"),
            status_code=resp.status_code,
            raw=data,
        )

    @staticmethod
    def _safe_json(resp: requests.Response) -> dict:
        try:
            return resp.json()
        except Exception:
            return {"text": resp.text}

    def close(self) -> None:
        """Close the underlying session."""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"Client(base_url={self._base_url!r})"
