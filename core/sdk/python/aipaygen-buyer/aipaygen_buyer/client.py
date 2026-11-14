"""AiPayGen Buyer Client — auto-402 handling with policy engine and transaction tracking."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

from .models import CallResult, PaymentReceipt, SpendingStats, X402Info
from .policy import PolicyViolation, SpendingPolicy
from .x402 import create_payment_header, parse_402_headers

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.aipaygen.com"


class AiPayGenBuyer:
    """Synchronous buyer client for AiPayGen x402 APIs.

    Automatically detects 402 Payment Required responses, creates signed
    EIP-3009 payments, and retries the request with the X-Payment header.

    Usage::

        client = AiPayGenBuyer(
            private_key="0x...",
            max_price=0.05,
            daily_budget=5.0,
        )
        result = client.call("/ask", prompt="What is x402?")
        print(result.data)
        print(f"Paid: {result.paid}, Receipt: {result.receipt}")

    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        base_url: str = _DEFAULT_BASE_URL,
        max_price: float = 0.10,
        daily_budget: float = 10.0,
        monthly_budget: Optional[float] = None,
        policy: Optional[SpendingPolicy] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self._private_key = private_key or os.environ.get("AIPAYGEN_PRIVATE_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or os.environ.get("AIPAYGEN_API_KEY", "")
        self._policy = policy or SpendingPolicy(
            max_price_per_call=max_price,
            daily_budget=daily_budget,
            monthly_budget=monthly_budget,
        )
        self._receipts: list[PaymentReceipt] = []
        self._client = httpx.Client(timeout=timeout)

    def call(
        self,
        endpoint: str,
        method: str = "POST",
        auto_pay: bool = True,
        **kwargs: Any,
    ) -> CallResult:
        """Call an AiPayGen API endpoint with automatic 402 payment handling.

        Args:
            endpoint: API path (e.g., "/ask", "/summarize").
            method: HTTP method.
            auto_pay: If True, automatically pay 402s within policy limits.
            **kwargs: Passed as JSON body for POST, query params for GET.

        Returns:
            CallResult with response data and optional payment receipt.
        """
        url = urljoin(self._base_url + "/", endpoint.lstrip("/"))
        headers = self._build_headers()

        if method.upper() == "GET":
            resp = self._client.get(url, headers=headers, params=kwargs)
        else:
            resp = self._client.request(method.upper(), url, headers=headers, json=kwargs)

        # Not a 402 — return directly
        if resp.status_code != 402:
            return self._make_result(resp)

        # 402 received — attempt payment if auto_pay is on
        if not auto_pay:
            return self._make_result(resp, error="402 Payment Required (auto_pay=False)")

        if not self._private_key:
            return self._make_result(
                resp, error="402 Payment Required but no private key configured"
            )

        x402_info = parse_402_headers(resp.headers)
        if not x402_info:
            return self._make_result(resp, error="402 but missing x402 headers")

        return self._handle_payment(url, method.upper(), kwargs, x402_info, endpoint)

    def _handle_payment(
        self,
        url: str,
        method: str,
        kwargs: dict,
        x402_info: X402Info,
        endpoint: str,
    ) -> CallResult:
        """Process x402 payment and retry the request."""
        price = x402_info.price_float

        # Check policy
        try:
            self._policy.check(price, x402_info.pay_to, endpoint)
        except PolicyViolation as e:
            return CallResult(
                status_code=402,
                error=f"Policy blocked payment: {e}",
                headers={},
            )

        # Create signed payment
        try:
            payment_header = create_payment_header(self._private_key, x402_info)
        except Exception as e:
            logger.error("Failed to create payment: %s", e)
            return CallResult(status_code=402, error=f"Payment signing failed: {e}")

        # Retry request with X-Payment header
        headers = self._build_headers()
        headers["X-Payment"] = payment_header

        if method == "GET":
            resp = self._client.get(url, headers=headers, params=kwargs)
        else:
            resp = self._client.request(method, url, headers=headers, json=kwargs)

        # Build receipt
        receipt = PaymentReceipt(
            endpoint=endpoint,
            price_usdc=x402_info.price_usdc,
            pay_to=x402_info.pay_to,
            network=x402_info.network,
            tx_hash=resp.headers.get("x-payment-receipt"),
            success=resp.is_success,
            error=None if resp.is_success else f"HTTP {resp.status_code}",
        )

        if resp.is_success:
            self._policy.record_spend(price)
            self._receipts.append(receipt)
            logger.info("Paid $%s USDC for %s", x402_info.price_usdc, endpoint)

        return self._make_result(resp, paid=True, receipt=receipt)

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def _make_result(
        resp: httpx.Response,
        paid: bool = False,
        receipt: Optional[PaymentReceipt] = None,
        error: Optional[str] = None,
    ) -> CallResult:
        try:
            data = resp.json()
        except Exception:
            data = resp.text
        return CallResult(
            status_code=resp.status_code,
            data=data,
            paid=paid,
            receipt=receipt,
            headers=dict(resp.headers),
            error=error,
        )

    @property
    def receipts(self) -> list[PaymentReceipt]:
        """All payment receipts from this session."""
        return list(self._receipts)

    @property
    def stats(self) -> SpendingStats:
        """Aggregated spending statistics."""
        total = sum(r.price_float for r in self._receipts if r.success)
        today = datetime.utcnow().date().isoformat()
        today_receipts = [
            r for r in self._receipts if r.timestamp.date().isoformat() == today and r.success
        ]
        return SpendingStats(
            total_spent_usdc=total,
            total_calls=len(self._receipts),
            calls_today=len(today_receipts),
            spent_today_usdc=sum(
                float(r.price_usdc.lstrip("$")) for r in today_receipts
            ),
            receipts=self._receipts,
        )

    @property
    def budget_remaining(self) -> float:
        """Remaining daily budget in USDC."""
        return self._policy.budget_remaining_today

    def discover(self) -> dict:
        """Fetch the /.well-known/x402 discovery endpoint."""
        resp = self._client.get(f"{self._base_url}/.well-known/x402")
        return resp.json()

    def catalog(self, search: Optional[str] = None, category: Optional[str] = None) -> dict:
        """Browse the API catalog."""
        params = {}
        if search:
            params["q"] = search
        if category:
            params["category"] = category
        resp = self._client.get(f"{self._base_url}/discover", params=params)
        return resp.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AsyncAiPayGenBuyer:
    """Async buyer client for AiPayGen x402 APIs.

    Same interface as AiPayGenBuyer but uses httpx.AsyncClient.

    Usage::

        async with AsyncAiPayGenBuyer(private_key="0x...") as client:
            result = await client.call("/ask", prompt="What is x402?")

    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        base_url: str = _DEFAULT_BASE_URL,
        max_price: float = 0.10,
        daily_budget: float = 10.0,
        monthly_budget: Optional[float] = None,
        policy: Optional[SpendingPolicy] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self._private_key = private_key or os.environ.get("AIPAYGEN_PRIVATE_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or os.environ.get("AIPAYGEN_API_KEY", "")
        self._policy = policy or SpendingPolicy(
            max_price_per_call=max_price,
            daily_budget=daily_budget,
            monthly_budget=monthly_budget,
        )
        self._receipts: list[PaymentReceipt] = []
        self._client = httpx.AsyncClient(timeout=timeout)

    async def call(
        self,
        endpoint: str,
        method: str = "POST",
        auto_pay: bool = True,
        **kwargs: Any,
    ) -> CallResult:
        """Call an AiPayGen API endpoint with automatic 402 payment handling."""
        url = urljoin(self._base_url + "/", endpoint.lstrip("/"))
        headers = self._build_headers()

        if method.upper() == "GET":
            resp = await self._client.get(url, headers=headers, params=kwargs)
        else:
            resp = await self._client.request(method.upper(), url, headers=headers, json=kwargs)

        if resp.status_code != 402:
            return self._make_result(resp)

        if not auto_pay:
            return self._make_result(resp, error="402 Payment Required (auto_pay=False)")

        if not self._private_key:
            return self._make_result(
                resp, error="402 Payment Required but no private key configured"
            )

        x402_info = parse_402_headers(resp.headers)
        if not x402_info:
            return self._make_result(resp, error="402 but missing x402 headers")

        return await self._handle_payment(url, method.upper(), kwargs, x402_info, endpoint)

    async def _handle_payment(
        self,
        url: str,
        method: str,
        kwargs: dict,
        x402_info: X402Info,
        endpoint: str,
    ) -> CallResult:
        price = x402_info.price_float

        try:
            self._policy.check(price, x402_info.pay_to, endpoint)
        except PolicyViolation as e:
            return CallResult(status_code=402, error=f"Policy blocked payment: {e}")

        try:
            payment_header = create_payment_header(self._private_key, x402_info)
        except Exception as e:
            return CallResult(status_code=402, error=f"Payment signing failed: {e}")

        headers = self._build_headers()
        headers["X-Payment"] = payment_header

        if method == "GET":
            resp = await self._client.get(url, headers=headers, params=kwargs)
        else:
            resp = await self._client.request(method, url, headers=headers, json=kwargs)

        receipt = PaymentReceipt(
            endpoint=endpoint,
            price_usdc=x402_info.price_usdc,
            pay_to=x402_info.pay_to,
            network=x402_info.network,
            tx_hash=resp.headers.get("x-payment-receipt"),
            success=resp.is_success,
            error=None if resp.is_success else f"HTTP {resp.status_code}",
        )

        if resp.is_success:
            self._policy.record_spend(price)
            self._receipts.append(receipt)

        return self._make_result(resp, paid=True, receipt=receipt)

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def _make_result(resp, paid=False, receipt=None, error=None) -> CallResult:
        try:
            data = resp.json()
        except Exception:
            data = resp.text
        return CallResult(
            status_code=resp.status_code,
            data=data,
            paid=paid,
            receipt=receipt,
            headers=dict(resp.headers),
            error=error,
        )

    @property
    def receipts(self) -> list[PaymentReceipt]:
        return list(self._receipts)

    @property
    def stats(self) -> SpendingStats:
        total = sum(r.price_float for r in self._receipts if r.success)
        today = datetime.utcnow().date().isoformat()
        today_receipts = [
            r for r in self._receipts if r.timestamp.date().isoformat() == today and r.success
        ]
        return SpendingStats(
            total_spent_usdc=total,
            total_calls=len(self._receipts),
            calls_today=len(today_receipts),
            spent_today_usdc=sum(float(r.price_usdc.lstrip("$")) for r in today_receipts),
            receipts=self._receipts,
        )

    @property
    def budget_remaining(self) -> float:
        return self._policy.budget_remaining_today

    async def discover(self) -> dict:
        resp = await self._client.get(f"{self._base_url}/.well-known/x402")
        return resp.json()

    async def catalog(self, search=None, category=None) -> dict:
        params = {}
        if search:
            params["q"] = search
        if category:
            params["category"] = category
        resp = await self._client.get(f"{self._base_url}/discover", params=params)
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
