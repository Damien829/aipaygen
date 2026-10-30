"""x402 protocol handler — parse 402 headers, create EIP-3009 payment, submit to facilitator."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

from .models import X402Info

logger = logging.getLogger(__name__)

# USDC contract on Base Mainnet
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_DECIMALS = 6

# EIP-712 domain for USDC transferWithAuthorization on Base
USDC_DOMAIN = {
    "name": "USD Coin",
    "version": "2",
    "chainId": 8453,
    "verifyingContract": USDC_BASE,
}

TRANSFER_WITH_AUTH_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ],
}


def parse_402_headers(headers: httpx.Headers) -> Optional[X402Info]:
    """Extract x402 payment info from 402 response headers."""
    if headers.get("x-payment-required") != "true":
        return None
    price = headers.get("x-price-usdc")
    pay_to = headers.get("x-pay-to")
    if not price or not pay_to:
        return None
    return X402Info(
        price_usdc=price,
        pay_to=pay_to,
        network=headers.get("x-network", "eip155:8453"),
        facilitator_url=headers.get(
            "x-facilitator-url",
            "https://api.cdp.coinbase.com/platform/v2/x402",
        ),
    )


def create_payment_header(
    private_key: str,
    x402_info: X402Info,
) -> str:
    """Create a signed EIP-3009 TransferWithAuthorization for x402 payment.

    Returns the X-Payment header value (hex-encoded signed authorization).
    """
    account = Account.from_key(private_key)
    price_wei = int(x402_info.price_float * (10**USDC_DECIMALS))
    now = int(time.time())
    nonce = Account.create().key  # random 32 bytes as nonce

    message_data = {
        "from": account.address,
        "to": x402_info.pay_to,
        "value": price_wei,
        "validAfter": 0,
        "validBefore": now + 3600,  # 1 hour validity
        "nonce": nonce,
    }

    # Sign EIP-712 typed data
    signable = encode_typed_data(
        domain_data=USDC_DOMAIN,
        message_types=TRANSFER_WITH_AUTH_TYPES,
        message_data=message_data,
        primary_type="TransferWithAuthorization",
    )
    signed = Account.sign_message(signable, private_key=private_key)

    # Build the x402 payment payload (JSON, base64 or hex depending on facilitator)
    import json
    import base64

    payload = {
        "x402Version": 1,
        "scheme": "exact",
        "network": x402_info.network,
        "payload": {
            "signature": signed.signature.hex(),
            "authorization": {
                "from": account.address,
                "to": x402_info.pay_to,
                "value": str(price_wei),
                "validAfter": "0",
                "validBefore": str(now + 3600),
                "nonce": nonce.hex(),
            },
        },
    }

    return base64.b64encode(json.dumps(payload).encode()).decode()


def submit_to_facilitator(
    facilitator_url: str,
    payment_header: str,
    http_client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    """Submit payment to the x402 facilitator for settlement verification.

    The facilitator verifies the signed authorization and settles the USDC transfer.
    Returns the facilitator response dict.
    """
    client = http_client or httpx.Client(timeout=30)
    try:
        resp = client.post(
            facilitator_url,
            json={"payment": payment_header},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Facilitator error %s: %s", e.response.status_code, e.response.text)
        return {"error": str(e), "status": e.response.status_code}
    except Exception as e:
        logger.error("Facilitator request failed: %s", e)
        return {"error": str(e)}
    finally:
        if http_client is None:
            client.close()


async def async_submit_to_facilitator(
    facilitator_url: str,
    payment_header: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Async version of submit_to_facilitator."""
    client = http_client or httpx.AsyncClient(timeout=30)
    try:
        resp = await client.post(
            facilitator_url,
            json={"payment": payment_header},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Facilitator error %s: %s", e.response.status_code, e.response.text)
        return {"error": str(e), "status": e.response.status_code}
    except Exception as e:
        logger.error("Facilitator request failed: %s", e)
        return {"error": str(e)}
    finally:
        if http_client is None:
            await client.aclose()
