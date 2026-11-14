"""API key management for AiPayGen SDK."""

from __future__ import annotations

import os
from typing import Optional


def resolve_api_key(api_key: Optional[str] = None) -> str:
    """Resolve API key from argument, env var, or raise."""
    key = api_key or os.environ.get("AIPAYGEN_API_KEY", "")
    if not key:
        raise ValueError(
            "API key required. Pass api_key= or set AIPAYGEN_API_KEY env var."
        )
    return key


def build_auth_headers(api_key: str) -> dict:
    """Build authorization headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
