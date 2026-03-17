"""Admin Tools — API key management, credits, balance, notifications, wallet, webhooks, stats."""

import os
import hashlib
from typing import Annotated
from pydantic import Field

from mcp_tools import mcp, metered_tool, _log, get_free_tier_remaining
import requests as _mcp_requests


# ── API Key Management ───────────────────────────────────────────────────────

@metered_tool("free")
def check_api_key_balance(key: Annotated[str, Field(description="API key to check balance for")]) -> dict:
    """Check balance and usage stats for a prepaid AiPayGen API key."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/auth/status?key={key}",
            headers={"Authorization": f"Bearer {key}"}, timeout=5)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Agent Builder & Account Tools ────────────────────────────────────────────

@metered_tool("free")
def check_balance() -> dict:
    """Check your API key balance and usage stats. Requires AIPAYGEN_API_KEY env var."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    if not api_key:
        return {"error": "AIPAYGEN_API_KEY env var not set"}
    try:
        resp = _mcp_requests.get("http://localhost:5001/auth/status",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("free")
def check_notifications() -> dict:
    """Check your unread notifications (payment confirmations, low balance alerts, referral bonuses). Requires AIPAYGEN_API_KEY env var."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    if not api_key:
        return {"error": "AIPAYGEN_API_KEY env var not set"}
    try:
        resp = _mcp_requests.get("http://localhost:5001/auth/notifications",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("free")
def list_models() -> dict:
    """List all available AI models with their providers and capabilities."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/models", timeout=5)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Monetization Tools (FREE — no metering) ─────────────────────────────────

@mcp.tool()
def buy_credits(
    amount: Annotated[int, Field(description="Amount in USD (1, 5, 10, 15, 20, 25, or 50)")]
) -> dict:
    """Get a payment link to buy API credits with a credit card. Starts at $1. Returns a Stripe checkout URL — share it with the user to complete payment."""
    valid_amounts = (1, 5, 10, 15, 20, 25, 50)
    if amount not in valid_amounts:
        return {"error": "invalid_amount", "message": f"Amount must be one of {valid_amounts}.", "hint": "Try buy_credits(amount=5) for $5 in credits."}
    try:
        resp = _mcp_requests.post(
            "http://localhost:5001/stripe/create-checkout",
            json={"amount": amount, "label": "mcp-purchase"},
            timeout=15,
        )
        data = resp.json()
        if resp.status_code != 200 or "url" not in data:
            return {"error": "checkout_failed", "message": data.get("error", "Could not create checkout session."), "hint": "Try again or visit https://api.aipaygen.com/docs"}
        return {
            "checkout_url": data["url"],
            "amount_usd": amount,
            "message": f"Open this link to complete your ${amount} credit purchase.",
            "note": "After payment, generate an API key with the generate_api_key tool.",
        }
    except Exception as exc:
        _log.error("buy_credits failed: %s", exc)
        return {"error": "checkout_failed", "message": "Could not reach payment service. Try again shortly.", "hint": "Visit https://api.aipaygen.com/docs for manual purchase."}


@mcp.tool()
def check_usage() -> dict:
    """Check your free tier usage and remaining calls for today."""
    api_key = os.getenv("AIPAYGEN_API_KEY", "")
    result = {"has_api_key": bool(api_key)}
    if api_key:
        try:
            resp = _mcp_requests.get(
                "http://localhost:5001/auth/key-status",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            data = resp.json()
            result["balance_usd"] = data.get("balance", 0)
            result["calls_remaining"] = "unlimited (prepaid key)"
            result["daily_limit"] = "unlimited"
            ref_code = data.get("referral_code", "")
            if not ref_code:
                import hashlib as _hl
                ref_code = _hl.sha256(api_key.encode()).hexdigest()[:8]
            if ref_code:
                result["referral_link"] = f"https://aipaygen.com/buy-credits?ref={ref_code}"
                result["referral_info"] = "Share your referral link — both you and the new user get $0.10 credits!"
        except Exception as exc:
            _log.error("check_usage key-status failed: %s", exc)
            result["balance_usd"] = "unknown"
            result["calls_remaining"] = "unknown"
    else:
        remaining = get_free_tier_remaining("mcp-user")
        result["calls_remaining"] = remaining
        result["daily_limit"] = 3
        result["upgrade_hint"] = "Run generate_api_key to get an API key, then buy_credits to add funds."
    return result


@metered_tool("free")
def generate_api_key(
    label: Annotated[str, Field(description="Label for your API key (e.g. 'my-project')")] = "mcp-key"
) -> dict:
    """Generate a free API key. Add credits later via buy_credits tool. Set AIPAYGEN_API_KEY env var to use it."""
    try:
        resp = _mcp_requests.post(
            "http://localhost:5001/auth/generate-key",
            json={"label": label, "source": "mcp-tool"},
            timeout=10,
        )
        data = resp.json()
        if resp.status_code != 200 or "key" not in data:
            return {"error": "key_generation_failed", "message": data.get("error", "Could not generate key."), "hint": "Visit https://api.aipaygen.com/docs"}
        api_key = data["key"]
        balance = data.get("balance_usd", 0)
        has_trial = balance > 0
        return {
            "api_key": api_key,
            "balance_usd": balance,
            "label": label,
            "setup": f'export AIPAYGEN_API_KEY={api_key}',
            "message": f"Key generated with ${balance:.2f} free trial credits (~{int(balance/0.006)} AI calls)! Set the env var above to unlock premium tools."
                       if has_trial else "Key generated! Set the env var above, then call buy_credits to add funds.",
            "next_step": "Call buy_credits(1) to add more credits when ready." if has_trial else "Call buy_credits(1) to add $1 in credits (~166 calls).",
        }
    except Exception as exc:
        _log.error("generate_api_key failed: %s", exc)
        return {"error": "key_generation_failed", "message": "Could not reach auth service. Try again shortly.", "hint": "Visit https://api.aipaygen.com/docs for manual key generation."}


# ── Crypto Deposit Tools ─────────────────────────────────────────────────────

@metered_tool("standard")
def get_crypto_deposit_info() -> dict:
    """Get crypto deposit information — wallet address, supported networks (Base/Solana), fees, limits."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/crypto/deposit", timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def create_deposit(
    network: Annotated[str, Field(description="Network: 'base' or 'solana'")] = "base",
    amount_usd: Annotated[float, Field(description="Expected deposit amount in USD")] = 10.0,
) -> dict:
    """Create a crypto deposit intent — returns unique address, QR code, and instructions."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    if not api_key:
        return {"error": "AIPAYGEN_API_KEY env var not set — required for deposit"}
    try:
        resp = _mcp_requests.post("http://localhost:5001/crypto/deposit", json={"api_key": api_key, "network": network, "amount": amount_usd}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def claim_deposit(
    tx_hash: Annotated[str, Field(description="Transaction hash to verify and claim")],
    api_key: Annotated[str, Field(description="API key to credit the deposit to")] = "",
    network: Annotated[str, Field(description="Network: 'base' or 'solana'")] = "base",
) -> dict:
    """Claim a crypto deposit by providing the transaction hash for onchain verification."""
    key = api_key or os.environ.get("AIPAYGEN_API_KEY", "")
    if not key:
        return {"error": "api_key required — provide it as a parameter or set AIPAYGEN_API_KEY env var"}
    try:
        resp = _mcp_requests.post("http://localhost:5001/crypto/claim", json={"api_key": key, "tx_hash": tx_hash, "network": network}, timeout=30)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def get_deposit_history(
    api_key: Annotated[str, Field(description="API key to check deposit history for")],
) -> dict:
    """Get deposit history for an API key."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/crypto/deposits", params={"api_key": api_key}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def get_deposit_address(
    api_key: Annotated[str, Field(description="API key to get a unique deposit address for")],
    network: Annotated[str, Field(description="Network: 'base' or 'solana'")] = "base",
) -> dict:
    """Get or create a unique deposit address for an API key on a specific network."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/crypto/address", params={"api_key": api_key, "network": network}, timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Wallet & Payments ────────────────────────────────────────────────────────

@metered_tool("standard")
def wallet_balance() -> dict:
    """Check your agent wallet balance (requires API key)."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/wallet/balance", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def wallet_transactions(limit: Annotated[int, Field(description="Number of recent transactions")] = 20) -> dict:
    """List recent wallet transactions."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/wallet/transactions", params={"limit": limit}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def wallet_create(agent_id: Annotated[str, Field(description="Agent ID to create wallet for")]) -> dict:
    """Create a new agent wallet for receiving payments."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/wallet/create", json={"agent_id": agent_id}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def wallet_list() -> dict:
    """List all agent wallets."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/wallet/list", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def wallet_fund(agent_id: Annotated[str, Field(description="Agent ID to fund")], amount: Annotated[float, Field(description="Amount in USD to add")]) -> dict:
    """Add funds to an agent wallet."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/wallet/fund", json={"agent_id": agent_id, "amount": amount}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def wallet_analytics() -> dict:
    """View wallet analytics: earnings, spending, and trends."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/wallet/analytics", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def wallet_policy(agent_id: Annotated[str, Field(description="Agent ID to set policy for")], max_per_call: Annotated[float, Field(description="Maximum spend per API call")] = 0.10, daily_limit: Annotated[float, Field(description="Daily spending limit")] = 5.0) -> dict:
    """Set spending policy for an agent wallet."""
    try:
        resp = _mcp_requests.patch("http://localhost:5001/wallet/policy", json={"agent_id": agent_id, "max_per_call": max_per_call, "daily_limit": daily_limit}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Webhook Management ───────────────────────────────────────────────────────

@metered_tool("standard")
def create_webhook(url: Annotated[str, Field(description="URL to receive webhook events")], events: Annotated[list, Field(description="List of event types to subscribe to")] = None) -> dict:
    """Create a webhook endpoint to receive event notifications."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/webhooks/create", json={"url": url, "events": events or ["all"]}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def list_webhooks(agent_id: Annotated[str, Field(description="Agent ID to list webhooks for")] = "default") -> dict:
    """List all registered webhooks for an agent."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/webhooks/list/{agent_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── File Storage Tools ───────────────────────────────────────────────────────

@metered_tool("standard")
def file_upload(filename: Annotated[str, Field(description="Name for the file")], content: Annotated[str, Field(description="File content (text or base64-encoded)")], content_type: Annotated[str, Field(description="MIME type")] = "text/plain") -> dict:
    """Upload a file to AiPayGen storage. Returns a file ID for retrieval."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/files/upload", json={"filename": filename, "content": content, "content_type": content_type}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def file_list(agent_id: Annotated[str, Field(description="Agent ID to list files for")] = "default") -> dict:
    """List all files stored by an agent."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/files/list/{agent_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def file_get(file_id: Annotated[str, Field(description="File ID to retrieve")]) -> dict:
    """Retrieve a stored file by its ID."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/files/{file_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Referral System ──────────────────────────────────────────────────────────

@mcp.tool()
def referral_stats(agent_id: Annotated[str, Field(description="Agent ID to check referral stats for")]) -> dict:
    """Check your referral stats: clicks, conversions, and earnings."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/referral/stats/{agent_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@mcp.tool()
def referral_leaderboard() -> dict:
    """View the referral leaderboard — top referrers by conversions."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/referral/leaderboard", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Economy & Stats ──────────────────────────────────────────────────────────

@mcp.tool()
def platform_stats() -> dict:
    """Get AiPayGen platform statistics: tools, agents, skills, APIs, and usage."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/stats", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@mcp.tool()
def popular_tools(limit: Annotated[int, Field(description="Number of top tools to return")] = 20) -> dict:
    """Get the most popular tools ranked by usage count."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/popular", params={"limit": limit}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@mcp.tool()
def economy_status() -> dict:
    """View the platform economy: total transactions, active agents, revenue metrics."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/economy/status", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Free Tier Status ─────────────────────────────────────────────────────────

@mcp.tool()
def free_tier_status() -> dict:
    """Check how many free calls remain today."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/free-tier/status", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Blog ─────────────────────────────────────────────────────────────────────

@metered_tool("standard")
def blog_list() -> dict:
    """List all blog posts on the AiPayGen blog."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/blog", timeout=10, headers={"Accept": "application/json"})
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def blog_read(slug: Annotated[str, Field(description="Blog post slug to read")]) -> dict:
    """Read a blog post by its slug."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/blog/{slug}", timeout=10, headers={"Accept": "application/json"})
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Health & Costs ───────────────────────────────────────────────────────────

@mcp.tool()
def health_history() -> dict:
    """View service health check history."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/health/history", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@mcp.tool()
def costs_summary() -> dict:
    """View your API usage costs breakdown."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/costs", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── RSS Feed ─────────────────────────────────────────────────────────────────

@mcp.tool()
def rss_feed() -> dict:
    """Get the AiPayGen RSS feed (latest updates and blog posts)."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/feed.xml", timeout=10)
        return {"content_type": "application/xml", "data": resp.text[:5000]}
    except Exception:
        return {"error": "Tool execution failed"}
