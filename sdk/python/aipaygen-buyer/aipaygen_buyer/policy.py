"""Spending policy engine — limits, allowlists, rate controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class SpendingPolicy:
    """Controls what the buyer SDK is allowed to spend.

    Args:
        max_price_per_call: Maximum USDC per single API call. Rejects if exceeded.
        daily_budget: Maximum total USDC spend per calendar day.
        monthly_budget: Maximum total USDC spend per calendar month.
        vendor_allowlist: If set, only pay these wallet addresses.
        vendor_blocklist: Never pay these wallet addresses.
        endpoint_allowlist: If set, only pay for these endpoint paths.
        require_confirmation: If True, raises PolicyConfirmationRequired instead of auto-paying.
    """

    max_price_per_call: float = 1.0
    daily_budget: float = 10.0
    monthly_budget: Optional[float] = None
    vendor_allowlist: Optional[set[str]] = None
    vendor_blocklist: set[str] = field(default_factory=set)
    endpoint_allowlist: Optional[set[str]] = None
    require_confirmation: bool = False

    def __post_init__(self):
        self._daily_spend: dict[str, float] = {}  # date_str -> amount
        self._monthly_spend: dict[str, float] = {}  # YYYY-MM -> amount

    def check(self, price: float, pay_to: str, endpoint: str) -> None:
        """Validate a payment against policy. Raises PolicyViolation on failure."""
        if price > self.max_price_per_call:
            raise PolicyViolation(
                f"Price ${price:.4f} exceeds max_price_per_call ${self.max_price_per_call:.4f}"
            )

        today = date.today().isoformat()
        daily_total = self._daily_spend.get(today, 0.0) + price
        if daily_total > self.daily_budget:
            raise PolicyViolation(
                f"Payment would exceed daily budget: "
                f"${self._daily_spend.get(today, 0.0):.4f} spent + ${price:.4f} > ${self.daily_budget:.4f}"
            )

        if self.monthly_budget is not None:
            month_key = datetime.utcnow().strftime("%Y-%m")
            monthly_total = self._monthly_spend.get(month_key, 0.0) + price
            if monthly_total > self.monthly_budget:
                raise PolicyViolation(
                    f"Payment would exceed monthly budget: ${self.monthly_budget:.4f}"
                )

        if self.vendor_allowlist is not None and pay_to.lower() not in {
            v.lower() for v in self.vendor_allowlist
        }:
            raise PolicyViolation(f"Vendor {pay_to} not in allowlist")

        if pay_to.lower() in {v.lower() for v in self.vendor_blocklist}:
            raise PolicyViolation(f"Vendor {pay_to} is blocklisted")

        if self.endpoint_allowlist is not None and endpoint not in self.endpoint_allowlist:
            raise PolicyViolation(f"Endpoint {endpoint} not in allowlist")

        if self.require_confirmation:
            raise PolicyConfirmationRequired(
                f"Policy requires confirmation for ${price:.4f} to {endpoint}"
            )

    def record_spend(self, price: float) -> None:
        """Record a successful payment against budget tracking."""
        today = date.today().isoformat()
        self._daily_spend[today] = self._daily_spend.get(today, 0.0) + price
        month_key = datetime.utcnow().strftime("%Y-%m")
        self._monthly_spend[month_key] = self._monthly_spend.get(month_key, 0.0) + price

    @property
    def spent_today(self) -> float:
        return self._daily_spend.get(date.today().isoformat(), 0.0)

    @property
    def budget_remaining_today(self) -> float:
        return max(0.0, self.daily_budget - self.spent_today)


class PolicyViolation(Exception):
    """Raised when a payment would violate spending policy."""


class PolicyConfirmationRequired(PolicyViolation):
    """Raised when policy requires manual confirmation before paying."""
