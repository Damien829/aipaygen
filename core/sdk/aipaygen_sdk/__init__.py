"""AiPayGen SDK — Python client for AiPayGen APIs with auto-402 payment handling."""

__version__ = "0.1.0"

from .client import Client
from .async_client import AsyncClient
from .exceptions import AiPayGenError, AuthError, PaymentRequired, RateLimitError, ServerError
from .types import ToolResult, PaymentReceipt, StreamChunk, X402PaymentInfo

__all__ = [
    "Client",
    "AsyncClient",
    "AiPayGenError",
    "AuthError",
    "PaymentRequired",
    "RateLimitError",
    "ServerError",
    "ToolResult",
    "PaymentReceipt",
    "StreamChunk",
    "X402PaymentInfo",
]
