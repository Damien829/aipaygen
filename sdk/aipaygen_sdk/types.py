"""Response and result types for AiPayGen SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolResult:
    """Result from a tool call."""

    result: Any = None
    error: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    status_code: int = 200
    paid: bool = False
    receipt: Optional[PaymentReceipt] = None
    raw: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300

    def __str__(self) -> str:
        if self.error:
            return f"ToolResult(error={self.error!r})"
        return f"ToolResult(result={self.result!r})"


@dataclass
class PaymentReceipt:
    """Receipt for an x402 payment."""

    endpoint: str = ""
    amount_usdc: str = "0"
    pay_to: str = ""
    network: str = ""
    tx_hash: Optional[str] = None
    success: bool = False


@dataclass
class StreamChunk:
    """A single chunk from a streaming response."""

    data: str = ""
    event: Optional[str] = None
    done: bool = False


@dataclass
class X402PaymentInfo:
    """Payment details extracted from a 402 response."""

    price: str = "0"
    pay_to: str = ""
    network: str = ""
    token: str = "USDC"
    description: str = ""

    @property
    def price_float(self) -> float:
        try:
            return float(self.price.lstrip("$"))
        except (ValueError, AttributeError):
            return 0.0
