"""Pydantic models for x402 payment responses, receipts, and policies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class X402Info(BaseModel):
    """Parsed x402 payment requirements from 402 response headers."""

    price_usdc: str = Field(description="Price in USDC for the call")
    pay_to: str = Field(description="Wallet address to pay")
    network: str = Field(default="eip155:8453", description="Chain network identifier")
    facilitator_url: str = Field(
        default="https://api.cdp.coinbase.com/platform/v2/x402",
        description="Facilitator endpoint for payment processing",
    )
    usdc_contract: str = Field(
        default="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        description="USDC contract address on Base",
    )

    @property
    def price_float(self) -> float:
        """Price as a float, stripping any '$' prefix."""
        return float(self.price_usdc.lstrip("$"))


class PaymentReceipt(BaseModel):
    """Record of a completed x402 payment."""

    endpoint: str
    price_usdc: str
    pay_to: str
    network: str
    tx_hash: Optional[str] = None
    facilitator_response: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    success: bool = True
    error: Optional[str] = None


class CallResult(BaseModel):
    """Result of an API call, including payment details if a 402 was handled."""

    status_code: int
    data: Any = None
    paid: bool = False
    receipt: Optional[PaymentReceipt] = None
    headers: dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class SpendingStats(BaseModel):
    """Aggregated spending statistics."""

    total_spent_usdc: float = 0.0
    total_calls: int = 0
    calls_today: int = 0
    spent_today_usdc: float = 0.0
    receipts: list[PaymentReceipt] = Field(default_factory=list)
