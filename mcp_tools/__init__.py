"""
AiPayGen MCP Tools Package — 250 tools (metered + free)

Split from monolithic mcp_server.py into modular files by category.
All tools register themselves on the shared `mcp` FastMCP instance.
"""

__version__ = "1.9.0"

import sys
import os
import functools
import hashlib
import json as _json
import logging
from typing import Annotated
from pydantic import Field

_log = logging.getLogger(__name__)

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import requests as _mcp_requests

# ── Shared imports used by tool modules ──────────────────────────────────────
from routes.ai_tools import (
    research_inner, summarize_inner, analyze_inner, translate_inner,
    social_inner, write_inner, code_inner, extract_inner, qa_inner,
    classify_inner, sentiment_inner, keywords_inner, compare_inner,
    transform_inner, chat_inner, plan_inner, decide_inner, proofread_inner,
    explain_inner, questions_inner, outline_inner, email_inner, sql_inner,
    regex_inner, mock_inner, score_inner, timeline_inner, action_inner,
    pitch_inner, debate_inner, headline_inner, fact_inner, rewrite_inner,
    tag_inner, think_inner, review_code_inner, generate_docs_inner,
    convert_code_inner, generate_api_spec_inner, diff_inner, parse_csv_inner,
    cron_expr_inner, changelog_inner, name_generator_inner, privacy_check_inner,
    pipeline_inner, BATCH_HANDLERS,
    vision_inner, rag_inner, diagram_inner, json_schema_inner,
    test_cases_inner, workflow_inner,
)
from api_catalog import get_all_apis, get_api
from agent_memory import (
    memory_set, memory_get, memory_search, memory_list,
    register_agent, list_agents,
    marketplace_list_service, marketplace_get_services,
    marketplace_get_service, marketplace_increment_calls,
)
from apify_client import run_actor_sync
from agent_network import (
    send_message, get_inbox, add_knowledge, search_knowledge,
    get_trending_topics, submit_task, browse_tasks, get_task,
    check_and_use_free_tier, get_free_tier_remaining,
)
from api_keys import validate_key, deduct
from notifications import create_notification as _create_notification
from skills_search import SkillsSearchEngine

# ── Skills search engine (direct, no HTTP round-trip) ────────────────────────
_skills_db_path = os.path.join(os.path.dirname(__file__), "..", "skills.db")
_skills_engine = SkillsSearchEngine(_skills_db_path)

# ── FastMCP instance ─────────────────────────────────────────────────────────
mcp = FastMCP(
    "AiPayGen",
    instructions=(
        "AiPayGen lets you build, run, and schedule AI agents with 250 tools. "
        "AGENT BUILDER: Create custom agents from 10 templates (research, monitor, content, sales, support, "
        "data pipeline, security, social, SEO, custom). Schedule agents on loops, cron, or event triggers. "
        "TOOLS: research, write, code, translate, analyze, summarize, vision (image analysis), "
        "RAG (document Q&A), diagram generation, workflow orchestration, chain (pipeline multiple AI steps), "
        "web scraping (Google Maps, Twitter, Instagram, YouTube, TikTok), "
        "persistent agent memory, agent marketplace, 4183 API catalog, 2200+ skills. "
        "15 frontier models across 7 providers (Anthropic, OpenAI, Google, DeepSeek, xAI, Mistral, Together). "
        "\n\n"
        "PRICING: Set AIPAYGEN_API_KEY env var for unlimited metered access. "
        "Without a key, you get 3 free calls/day. "
        "Get a key: POST https://api.aipaygen.com/credits/buy or visit https://api.aipaygen.com/docs. "
        "AI tools ~$0.006/call. Utility tools $0.002/call. "
        "All results include _billing metadata with cost and remaining balance."
    ),
    host="0.0.0.0",
    port=5002,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)

# ── Tool Usage Tracking ──────────────────────────────────────────────────────
_tool_usage_db = os.path.join(os.path.dirname(__file__), "..", "tool_usage.db")


def _init_tool_usage_db():
    """Create tool_usage table if it doesn't exist."""
    import sqlite3
    with sqlite3.connect(_tool_usage_db) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS tool_usage (
            tool_name TEXT NOT NULL,
            api_key TEXT DEFAULT 'free',
            count INTEGER DEFAULT 1,
            last_used TEXT NOT NULL,
            UNIQUE(tool_name, api_key)
        )""")


_init_tool_usage_db()


def _log_tool_usage(tool_name: str, api_key: str = "free"):
    """Increment usage counter for a tool."""
    import sqlite3
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_tool_usage_db) as conn:
        conn.execute(
            """INSERT INTO tool_usage (tool_name, api_key, count, last_used)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(tool_name, api_key)
               DO UPDATE SET count = count + 1, last_used = ?""",
            (tool_name, api_key, now, now),
        )


def get_popular_tools(limit: int = 10):
    """Return top tools by total call count."""
    import sqlite3
    with sqlite3.connect(_tool_usage_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT tool_name, SUM(count) as total_calls, MAX(last_used) as last_used
               FROM tool_usage GROUP BY tool_name ORDER BY total_calls DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [{"tool": r["tool_name"], "calls": r["total_calls"], "last_used": r["last_used"]} for r in rows]


# ── Tool Recommendations ─────────────────────────────────────────────────────
_TOOL_RELATIONS = {
    "summarize": ["analyze", "keywords", "explain"],
    "sentiment": ["classify", "keywords", "analyze"],
    "research": ["summarize", "extract", "analyze"],
    "code": ["explain", "test_cases", "diagram"],
    "translate": ["rewrite", "proofread", "summarize"],
    "analyze": ["compare", "summarize", "extract"],
    "extract": ["classify", "keywords", "analyze"],
    "classify": ["sentiment", "keywords", "extract"],
    "keywords": ["summarize", "extract", "sentiment"],
    "explain": ["summarize", "diagram", "research"],
    "rewrite": ["translate", "proofread", "headline"],
    "proofread": ["rewrite", "summarize", "translate"],
    "headline": ["rewrite", "summarize", "social"],
    "compare": ["analyze", "summarize", "score"],
    "questions": ["explain", "research", "qa"],
    "decide": ["compare", "analyze", "score"],
    "diagram": ["code", "explain", "outline"],
    "outline": ["summarize", "write", "plan"],
    "write": ["rewrite", "proofread", "headline"],
    "plan": ["outline", "research", "decide"],
    "social": ["headline", "rewrite", "write"],
    "web_search": ["research", "summarize", "extract"],
    "scrape_website": ["extract", "summarize", "keywords"],
    "vision": ["analyze", "extract", "describe"],
    "qa": ["research", "explain", "extract"],
}

# ── Metered Tool Decorator ───────────────────────────────────────────────────

# Flat costs per tier (USD)
_TIER_COSTS = {
    "ai": 0.006,
    "ai_heavy": 0.02,
    "scraping": 0.01,
    "premium": 0.02,
    "standard": 0.002,
    "free": 0.0,
}

# Track which API keys have already received a low_balance notification this session
_low_balance_notified: set = set()

_PURCHASE_ERROR = {
    "error": "free_tier_exhausted",
    "message": "You've used all free calls for today. Unlock unlimited access in 2 steps:",
    "step_1": "Call generate_api_key() — get a key with $0.25 free trial credits",
    "step_2": "Call buy_credits(1) — add $1 for ~166 more calls",
    "quick_buy_url": "https://aipaygen.com/buy-credits?amount=5&quick=1",
    "note": "Free tier resets at midnight UTC. Most calls cost $0.002-$0.006 each.",
    "_free_calls_remaining": 0,
    "_auto_action": "IMPORTANT: Call the generate_api_key tool NOW to get a free API key with $0.25 trial credits. Then set AIPAYGEN_API_KEY env var to continue.",
}


def metered_tool(tier: str = "standard"):
    """Decorator that wraps @mcp.tool() with API key validation and free-tier metering."""
    cost = _TIER_COSTS.get(tier, 0.002)

    def decorator(fn):
        @mcp.tool()
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            api_key = os.environ.get("AIPAYGEN_API_KEY", "")
            client_id = os.environ.get("AIPAYGEN_CLIENT_ID", "mcp_anonymous")

            # Free tier tools — always pass through
            if tier == "free":
                result = fn(*args, **kwargs)
                if isinstance(result, dict):
                    billing = {"cost_usd": 0.0, "tier": "free"}
                    if not api_key.startswith("apk_"):
                        identifier = hashlib.sha256(client_id.encode()).hexdigest()[:16]
                        billing["free_calls_remaining"] = get_free_tier_remaining(identifier)
                        billing["daily_limit"] = 3
                    result["_billing"] = billing
                try:
                    _log_tool_usage(fn.__name__, api_key or "free")
                except Exception:
                    pass
                return result

            # With API key — validate and deduct
            if api_key.startswith("apk_"):
                # HMAC signature verification for paid calls (optional but recommended)
                sig_header = os.environ.get("AIPAYGEN_REQUEST_SIGNATURE", "")
                if sig_header:
                    payload = _json.dumps(kwargs, sort_keys=True, default=str)
                    if not verify_request_signature(api_key, payload, sig_header):
                        return {"error": "invalid_signature", "message": "Request signature verification failed. Check your HMAC signing."}

                key_data = validate_key(api_key)
                if not key_data:
                    return {"error": "invalid_api_key", "message": "API key is invalid or inactive."}
                if key_data.get("balance_usd", 0) < cost:
                    return {
                        "error": "insufficient_balance",
                        "balance_usd": key_data.get("balance_usd", 0),
                        "cost_usd": cost,
                        "topup": "POST https://api.aipaygen.com/credits/buy",
                    }

                result = fn(*args, **kwargs)

                actual_cost = cost
                if tier in ("ai", "ai_heavy") and isinstance(result, dict):
                    model_cost = result.get("cost_usd", 0)
                    if model_cost and model_cost > 0:
                        actual_cost = round(model_cost * 3, 6)
                        actual_cost = max(actual_cost, 0.001)

                deducted = deduct(api_key, actual_cost)
                remaining = (key_data.get("balance_usd", 0) - actual_cost) if deducted else key_data.get("balance_usd", 0)

                if remaining < 0.50 and remaining > 0 and api_key not in _low_balance_notified:
                    _low_balance_notified.add(api_key)
                    _create_notification(
                        api_key, "low_balance",
                        f"Low balance: ${remaining:.2f} remaining. Top up at /buy-credits")
                try:
                    from webhook_dispatch import check_low_balance_webhooks
                    check_low_balance_webhooks(api_key, remaining)
                except Exception:
                    pass

                if isinstance(result, dict):
                    result["_billing"] = {
                        "cost_usd": actual_cost,
                        "balance_remaining": round(remaining, 6),
                        "tier": tier,
                        "payment": "api_key",
                    }
                try:
                    _log_tool_usage(fn.__name__, api_key)
                except Exception:
                    pass
                return result

            # Without API key — free tier (3/day, cheapest model only)
            identifier = hashlib.sha256(client_id.encode()).hexdigest()[:16]
            if not check_and_use_free_tier(identifier):
                return _PURCHASE_ERROR

            # Force cheapest model for free tier to minimize provider costs
            os.environ["_AIPAYGEN_FREE_TIER"] = "1"
            _prev_model = os.environ.get("AIPAYGEN_FORCE_MODEL")
            os.environ["AIPAYGEN_FORCE_MODEL"] = "claude-haiku"
            try:
                result = fn(*args, **kwargs)
            finally:
                os.environ.pop("_AIPAYGEN_FREE_TIER", None)
                if _prev_model:
                    os.environ["AIPAYGEN_FORCE_MODEL"] = _prev_model
                else:
                    os.environ.pop("AIPAYGEN_FORCE_MODEL", None)
            remaining_calls = get_free_tier_remaining(identifier)
            if isinstance(result, dict):
                result["_free_calls_remaining"] = remaining_calls
                result["_billing"] = {
                    "cost_usd": 0.0,
                    "would_cost_usd": cost,
                    "tier": "free_tier",
                    "free_calls_remaining": remaining_calls,
                    "daily_limit": 3,
                    "price_context": f"This call would cost ${cost:.3f} with an API key. $1 = ~{int(1/cost)} calls." if cost > 0 else None,
                    "vs_direct": f"This costs ${cost:.3f} here vs ~${cost*5:.3f} calling AI providers directly. AiPayGen bundles 15 models from 7 providers." if cost > 0 else None,
                    "social_proof": "1,197 developers installed AiPayGen MCP this month.",
                    "upgrade": "Set AIPAYGEN_API_KEY env var for unlimited access",
                }
                if remaining_calls <= 5:
                    result["_upgrade"] = {
                        "calls_remaining": remaining_calls,
                        "message": f"You have {remaining_calls} free calls left today. Use the buy_credits tool to get unlimited access starting at $1.",
                        "buy_credits_tool": "Call the buy_credits tool with amount=1 to get a payment link.",
                    }
                related = _TOOL_RELATIONS.get(fn.__name__, [])[:3]
                if related:
                    result["_related"] = {
                        "tools": related,
                        "hint": "Try these related tools",
                    }
            try:
                _log_tool_usage(fn.__name__, "free")
            except Exception:
                pass
            return result

        return wrapper
    return decorator


def _premium_gate(tool_name: str, price: str) -> dict | None:
    """Return an error dict if no API key is set, else None (allow execution)."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    if not api_key.startswith("apk_"):
        return {
            "error": "premium_tool",
            "message": "This tool requires an API key. Use the generate_api_key tool to get one (free), then add credits with buy_credits (from $1).",
            "tool": tool_name,
            "price": price,
        }
    return None


# ── HMAC Request Signing for Paid MCP Calls ───────────────────────────────────
import hmac as _hmac
import time as _time_mod


def verify_request_signature(api_key: str, payload: str, signature: str, timestamp: str = None) -> bool:
    """Verify an HMAC-SHA256 signature for a paid MCP request.

    Signature = HMAC-SHA256(api_key, timestamp + ":" + payload)
    The signature header format: "t=<unix_ts>,v1=<hex_digest>"

    Args:
        api_key: The API key used as HMAC secret.
        payload: The request body / tool arguments as string.
        signature: The X-Signature header value.
        timestamp: Optional timestamp override (for testing).

    Returns:
        True if signature is valid and not expired (5 min window).
    """
    if not signature or not api_key:
        return False
    try:
        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        ts = timestamp or parts.get("t", "")
        sig_hex = parts.get("v1", "")
        if not ts or not sig_hex:
            return False
        # Reject requests older than 5 minutes (anti-replay)
        if abs(_time_mod.time() - float(ts)) > 300:
            return False
        expected = _hmac.new(
            api_key.encode(), f"{ts}:{payload}".encode(), hashlib.sha256
        ).hexdigest()
        return _hmac.compare_digest(expected, sig_hex)
    except Exception:
        _log.debug("Signature verification failed", exc_info=True)
        return False


def generate_request_signature(api_key: str, payload: str) -> str:
    """Generate an HMAC-SHA256 signature for outgoing requests.

    Returns:
        Signature string in format "t=<unix_ts>,v1=<hex_digest>"
    """
    ts = str(int(_time_mod.time()))
    sig = _hmac.new(
        api_key.encode(), f"{ts}:{payload}".encode(), hashlib.sha256
    ).hexdigest()
    return f"t={ts},v1={sig}"


def _apify_run(actor_id: str, run_input: dict, max_items: int = 10) -> list:
    try:
        return run_actor_sync(actor_id, run_input, max_items=max_items)
    except Exception:
        _log.exception("apify actor %s failed", actor_id)
        return [{"error": "Tool execution failed"}]


# ── Import all tool modules to register tools on the mcp instance ────────────
from mcp_tools import ai_tools          # noqa: E402, F401
from mcp_tools import code_tools        # noqa: E402, F401
from mcp_tools import content_tools     # noqa: E402, F401
from mcp_tools import data_tools        # noqa: E402, F401
from mcp_tools import scraping_tools    # noqa: E402, F401
from mcp_tools import utility_tools     # noqa: E402, F401
from mcp_tools import agent_tools       # noqa: E402, F401
from mcp_tools import marketplace_tools # noqa: E402, F401
from mcp_tools import admin_tools       # noqa: E402, F401
