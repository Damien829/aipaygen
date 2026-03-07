import os
import json
import uuid
import threading
import tempfile
import time as _time
import hashlib as _hashlib
from datetime import datetime
from cryptography.fernet import Fernet
from flask import Flask, request, jsonify, render_template_string, Response, stream_with_context
from dotenv import load_dotenv
import anthropic
import requests as _requests
from apscheduler.schedulers.background import BackgroundScheduler

# Shared utilities (extracted from this file)
from helpers import (
    cache_get as _cache_get, cache_set as _cache_set,
    check_rate_limit as _check_rate_limit,
    check_identity_rate_limit as _check_identity_rate_limit,
    get_client_ip as _get_client_ip,
    log_payment, parse_json_from_claude, agent_response,
    api_error as _api_error, require_admin,
)

from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync, PaymentOption
from x402.http.middleware.flask import payment_middleware
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServerSync
from web import scrape_url, search_web
from api_catalog import init_db, get_all_apis, get_api, get_recent_runs
from api_discovery import run_all_hunters  # run_all_agents removed, use run_all_hunters
from apify_client import run_actor_sync, get_run_status
from agent_memory import (
    init_memory_db, memory_set, memory_get, memory_search,
    memory_clear, register_agent, list_agents,
    marketplace_list_service, marketplace_get_services,
    marketplace_get_service, marketplace_increment_calls,
    marketplace_deregister,
)
from agent_network import (
    init_network_db, send_message, get_inbox, mark_read, broadcast_message,
    add_knowledge, search_knowledge, get_trending_topics, vote_knowledge,
    submit_task, browse_tasks, claim_task, complete_task, get_task,
    check_and_use_free_tier, get_free_tier_status,
    update_reputation, get_reputation, get_leaderboard,
    subscribe_tasks, get_task_subscribers,
)
from specialist_agents import bootstrap_all_agents
from api_keys import init_keys_db, generate_key, topup_key, get_key_status, validate_key, deduct, deduct_metered
from async_jobs import init_jobs_db, submit_job, get_job, run_job_async
from file_storage import init_files_db, save_file, get_file, delete_file, list_files, storage_stats
from webhook_relay import (
    init_webhooks_db, create_webhook, receive_webhook_event,
    get_webhook_events, list_webhooks, get_webhook,
)
from referral import (
    init_referral_db, register_referral_agent, record_click,
    record_conversion, get_referral_stats, get_referral_leaderboard,
)
from discovery_engine import (
    init_discovery_db, get_blog_post, list_blog_posts,
    generate_all_blog_posts, get_outreach_log,
    run_hourly, run_daily, run_weekly,
    run_canary, get_health_history,
    run_maintenance, register_db_paths,
    track_cost, get_daily_cost, is_cost_throttled,
)
from funnel_tracker import log_event as funnel_log_event, get_funnel_stats
from model_router import call_model, list_models, get_model_config, calculate_cost, resolve_model_name, ModelNotFoundError
from agent_identity import (
    generate_challenge, verify_challenge, verify_jwt,
    InvalidSignatureError, ChallengeExpiredError,
)
import io
import base64
import socket
import colorsys
import re as _re
import qrcode
import feedparser
from youtube_transcript_api import YouTubeTranscriptApi

# Cache, rate limiting, and IP utils now in helpers.py (imported at top)


# ── Cost-Aware Model Selection ────────────────────────────────────────────────
DAILY_COST_LIMIT_USD = float(os.getenv("DAILY_COST_LIMIT_USD", "10.0"))
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_THROTTLE_MODEL = "claude-haiku-4-5-20251001"  # already haiku; future: could cap max_tokens

def _get_model(preferred: str = None) -> str:
    """Return the model to use. Falls back to haiku if daily cost exceeded."""
    if is_cost_throttled(DAILY_COST_LIMIT_USD):
        return _THROTTLE_MODEL
    return preferred or _DEFAULT_MODEL

_key_path = os.path.expanduser("~/.agent_key")
_env_enc = os.path.join(os.path.dirname(__file__), ".env.enc")
_env_plain = os.path.join(os.path.dirname(__file__), ".env")

if os.path.exists(_env_enc) and os.path.exists(_key_path):
    _key = open(_key_path, "rb").read()
    _data = Fernet(_key).decrypt(open(_env_enc, "rb").read())
    # Parse decrypted env in memory — never write secrets to disk
    for _line in _data.decode("utf-8", errors="replace").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
    # Also load plain .env for any additional keys (won't override encrypted ones)
    if os.path.exists(_env_plain):
        load_dotenv(_env_plain, override=False)
else:
    load_dotenv(_env_plain)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB max request body

PAYMENTS_LOG = os.path.join(os.path.dirname(__file__), "payments.jsonl")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

import functools
import re as _re
# require_admin, _get_client_ip, log_payment now in helpers.py (imported at top)


# ── Refund credits table (for 500 errors after payment) ──────────────────────
_refund_db_path = os.path.join(os.path.dirname(__file__), "refunds.db")

def _init_refund_db():
    import sqlite3
    conn = sqlite3.connect(_refund_db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS refund_credits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        amount_usd REAL NOT NULL,
        endpoint TEXT,
        request_id TEXT,
        redeemed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

def _issue_refund_credit(amount_usd: float, endpoint: str = "", request_id: str = "") -> str:
    """Issue a one-time credit code for a refund. Returns the code."""
    import sqlite3
    code = "refund_" + uuid.uuid4().hex[:12]
    conn = sqlite3.connect(_refund_db_path)
    conn.execute(
        "INSERT INTO refund_credits (code, amount_usd, endpoint, request_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (code, amount_usd, endpoint, request_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return code

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x366D488a48de1B2773F3a21F1A6972715056Cb30")
EVM_NETWORK: Network = "eip155:8453"  # Base Mainnet
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://api.cdp.coinbase.com/platform/v2/x402")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://api.aipaygen.com")

import stripe as _stripe
if STRIPE_SECRET_KEY:
    _stripe.api_key = STRIPE_SECRET_KEY

CDP_API_KEY_ID = os.getenv("CDP_API_KEY_ID", "")
CDP_API_KEY_SECRET = os.getenv("CDP_API_KEY_SECRET", "")

def _cdp_create_headers():
    """Generate CDP JWT auth headers for x402 facilitator endpoints."""
    try:
        from cdp.auth import get_auth_headers, GetAuthHeadersOptions
    except ImportError:
        raise ImportError("cdp package required for CDP auth. Install with: pip install cdp-sdk")
    from urllib.parse import urlparse
    parsed = urlparse(FACILITATOR_URL)
    host = parsed.hostname
    base_path = parsed.path.rstrip("/")
    def _headers_for(method, path):
        return get_auth_headers(GetAuthHeadersOptions(
            api_key_id=CDP_API_KEY_ID,
            api_key_secret=CDP_API_KEY_SECRET,
            request_method=method,
            request_host=host,
            request_path=f"{base_path}{path}",
        ))
    return {
        "verify": _headers_for("POST", "/verify"),
        "settle": _headers_for("POST", "/settle"),
        "supported": _headers_for("GET", "/supported"),
    }

_cdp_available = False
if CDP_API_KEY_ID and CDP_API_KEY_SECRET:
    try:
        import cdp.auth  # noqa: F401
        _cdp_available = True
    except ImportError:
        pass

if _cdp_available:
    facilitator = HTTPFacilitatorClientSync(
        {"url": FACILITATOR_URL, "create_headers": _cdp_create_headers}
    )
else:
    facilitator = HTTPFacilitatorClientSync(
        FacilitatorConfig(url=FACILITATOR_URL)
    )
server = x402ResourceServerSync(facilitator)
server.register(EVM_NETWORK, ExactEvmServerScheme())

routes: dict[str, RouteConfig] = {
    "POST /scrape": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Fetch any URL and return clean markdown text ($0.01)",
    ),
    "POST /search": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="DuckDuckGo web search, returns top N results ($0.01)",
    ),
    "POST /research": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Deep research: search + scrape + Claude synthesis with citations ($0.05)",
    ),
    "POST /write": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude writes content (article, post, copy) to your spec ($0.02)",
    ),
    "POST /analyze": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude analyzes data or text and returns structured insights ($0.01)",
    ),
    "POST /code": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude generates code from a description in any language ($0.02)",
    ),
    "POST /summarize": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude summarizes long text or articles into key points ($0.01)",
    ),
    "POST /translate": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude translates text to any language ($0.01)",
    ),
    "POST /social": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude generates platform-optimized social media posts ($0.02)",
    ),
    "POST /batch": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Run up to 5 AI operations in one payment — research, write, analyze, translate, social, code ($0.03)",
    ),
    "POST /extract": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract structured data from any text using a schema you define ($0.01)",
    ),
    "POST /qa": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Answer a question given a context document — core RAG building block ($0.01)",
    ),
    "POST /classify": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Classify text into your defined categories with confidence scores ($0.01)",
    ),
    "POST /sentiment": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Deep sentiment analysis — polarity, emotions, confidence, key phrases ($0.01)",
    ),
    "POST /keywords": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract keywords, topics, tags, and entities from any text ($0.01)",
    ),
    "POST /compare": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Compare two texts — similarities, differences, recommendation ($0.01)",
    ),
    "POST /transform": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Transform text with any instruction — rewrite, reformat, clean, expand, condense ($0.01)",
    ),
    "POST /chat": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Stateless multi-turn chat — send message history, get Claude's reply ($0.02)",
    ),
    "POST /plan": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate a step-by-step action plan for any goal ($0.02)",
    ),
    "POST /decide": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Decision framework — pros/cons, risks, and a recommendation ($0.02)",
    ),
    "POST /proofread": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Grammar, spelling, clarity corrections with tracked changes ($0.01)",
    ),
    "POST /explain": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Explain any concept at beginner, intermediate, or expert level ($0.01)",
    ),
    "POST /questions": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate interview, FAQ, or quiz questions from any content ($0.01)",
    ),
    "POST /outline": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate a structured hierarchical outline from a topic or document ($0.01)",
    ),
    "POST /email": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Compose professional emails — subject, body, tone, length ($0.02)",
    ),
    "POST /sql": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Natural language to SQL — describe what you want, get a query ($0.02)",
    ),
    "POST /regex": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate regex patterns from plain English description ($0.01)",
    ),
    "POST /mock": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate realistic mock data — JSON, CSV, or plain list ($0.02)",
    ),
    "POST /score": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Score content quality on any custom rubric — returns per-criterion scores ($0.01)",
    ),
    "POST /timeline": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract or generate a chronological timeline of events from text ($0.01)",
    ),
    "POST /action": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract action items, tasks, and owners from meeting notes or text ($0.01)",
    ),
    "POST /pitch": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate elevator pitch — hook, value prop, call to action ($0.02)",
    ),
    "POST /debate": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Arguments for and against any position with strength ratings ($0.02)",
    ),
    "POST /headline": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate compelling headlines and titles for any content ($0.01)",
    ),
    "POST /fact": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract factual claims from text with source hints and verifiability scores ($0.01)",
    ),
    "POST /rewrite": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Rewrite text for a specific audience, reading level, or brand voice ($0.01)",
    ),
    "POST /tag": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Auto-tag content using a provided taxonomy or free-form tagging ($0.01)",
    ),
    "POST /pipeline": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Chain up to 5 operations where each step can use the previous output ($0.05)",
    ),
    "POST /api-call": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Proxy HTTP call to any cataloged API with optional Claude enrichment ($0.03)",
    ),
    "POST /scrape/google-maps": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape Google Maps places for any query — names, addresses, ratings ($0.05)",
    ),
    "POST /scrape/instagram": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape Instagram profile posts and metadata ($0.03)",
    ),
    "POST /scrape/tweets": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape tweets by search query or hashtag ($0.03)",
    ),
    "POST /scrape/linkedin": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape LinkedIn profile data ($0.05)",
    ),
    "POST /scrape/youtube": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape YouTube video metadata by search keyword ($0.03)",
    ),
    "POST /scrape/web": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Crawl any website and extract structured content ($0.03)",
    ),
    "POST /scrape/tiktok": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape TikTok profile videos and metadata ($0.03)",
    ),
    "POST /scrape/facebook-ads": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape Facebook Ad Library for any brand or keyword ($0.05)",
    ),
    "POST /scrape/actor": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Run any Apify actor by ID with custom input ($0.03)",
    ),
    "POST /vision": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Analyze any image URL with Claude Vision — describe, extract, or answer questions ($0.02)",
    ),
    "POST /rag": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Mini RAG — provide documents + query, get a grounded answer with citations ($0.02)",
    ),
    "POST /diagram": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate Mermaid diagrams (flowchart, sequence, erd, gantt, mindmap) from description ($0.02)",
    ),
    "POST /json-schema": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate JSON Schema (draft-07) from a plain English description ($0.01)",
    ),
    "POST /test-cases": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate comprehensive test cases for code or a feature description ($0.02)",
    ),
    "POST /workflow": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.10", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Multi-step agentic reasoning — Claude Sonnet breaks down and executes complex goals ($0.10)",
    ),
    "POST /memory/set": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Store a persistent memory value for an agent — survives across sessions ($0.01)",
    ),
    "POST /memory/get": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Retrieve a stored memory by agent_id and key ($0.01)",
    ),
    "POST /memory/search": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Search all memories for an agent by keyword — returns ranked matches ($0.01)",
    ),
    "POST /memory/clear": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Delete all memories for an agent_id ($0.01)",
    ),
    "POST /chain": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Chain up to 5 AI endpoints in sequence — each step can reference prior results ($0.05)",
    ),
    "POST /marketplace/call": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Proxy-call any agent marketplace listing — we handle routing and payment",
    ),
    "POST /message/send": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Send a direct message from one agent to another ($0.01)",
    ),
    "POST /message/broadcast": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Broadcast a message to all agents in the network ($0.01)",
    ),
    "POST /message/reply": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Reply to a message, preserving the thread ($0.01)",
    ),
    "POST /knowledge/add": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Add an entry to the shared agent knowledge base ($0.01)",
    ),
    "POST /task/submit": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Post a task to the agent task board ($0.01)",
    ),
    "POST /task/complete": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Mark a claimed task as complete and submit the result ($0.01)",
    ),
    "POST /code/run": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Execute Python code in a sandboxed subprocess, returns stdout/stderr ($0.02)",
    ),
    "GET /web/search": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="DuckDuckGo web search — instant answers + related results ($0.02)",
    ),
    "POST /enrich": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Entity enrichment — aggregate data about an IP, crypto, country, or company ($0.02)",
    ),
    "POST /credits/buy": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$5.00", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Buy $5 credit pack — returns prepaid API key for metered token-based billing",
    ),
}

_raw_flask_wsgi = app.wsgi_app  # save original Flask WSGI before x402 wraps it
payment_middleware(app, routes=routes, server=server)

# API key WSGI wrapper — intercepts Bearer apk_xxx before x402 checks
_x402_wsgi = app.wsgi_app


def _api_key_wsgi(environ, start_response):
    auth = environ.get("HTTP_AUTHORIZATION", "")
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "GET")
    route_key = f"{method} {path}"

    # Localhost bypass — local MCP server should not pay itself
    # Only bypass if truly local (no CF-Connecting-IP means not via tunnel)
    remote_addr = environ.get("REMOTE_ADDR", "")
    cf_ip = environ.get("HTTP_CF_CONNECTING_IP", "")
    if remote_addr in ("127.0.0.1", "::1") and not cf_ip and routes.get(route_key):
        return _raw_flask_wsgi(environ, start_response)

    # 0. Per-IP rate limit (60 req/min) — applied to AI route calls only
    if routes.get(route_key):
        try:
            # Trust CF-Connecting-IP (set by Cloudflare), fall back to REMOTE_ADDR
            _ip = (
                environ.get("HTTP_CF_CONNECTING_IP",
                    environ.get("REMOTE_ADDR", "unknown"))
            )
            if not _check_rate_limit(_ip):
                body = json.dumps({
                    "error": "rate_limited",
                    "message": "Too many requests. Limit: 60 per minute per IP.",
                    "retry_after_seconds": 60,
                }).encode()
                start_response("429 Too Many Requests", [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(body))),
                    ("Retry-After", "60"),
                    ("Access-Control-Allow-Origin", "https://aipaygen.com"),
                ])
                return [body]
        except Exception:
            pass

    # 1. Prepaid API key bypass (Bearer apk_xxx)
    if auth.startswith("Bearer apk_"):
        key = auth[7:]  # strip "Bearer "
        route_cfg = routes.get(route_key)
        pricing_mode = environ.get("HTTP_X_PRICING", "flat").lower()
        if route_cfg:
            try:
                if pricing_mode == "metered":
                    # Metered: validate key exists and has minimum balance
                    key_data = validate_key(key)
                    if key_data and key_data.get("balance_usd", 0) >= 0.001:
                        environ["X_APIKEY_BYPASS"] = key
                        environ["X_PRICING_MODE"] = "metered"
                        return _raw_flask_wsgi(environ, start_response)
                else:
                    # Flat: deduct fixed amount upfront (existing behavior)
                    price_str = route_cfg.accepts[0].price  # e.g. "$0.01"
                    cost = float(price_str.lstrip("$"))
                    key_data = validate_key(key)
                    if key_data and key_data.get("balance_usd", 0) >= cost:
                        # 20% bulk discount for prepaid keys with balance >= $2.00
                        if key_data.get("balance_usd", 0) >= 2.00:
                            cost = round(cost * 0.8, 4)
                        if deduct(key, cost):
                            environ["X_APIKEY_BYPASS"] = key
                            environ["X_PRICING_MODE"] = "flat"
                            return _raw_flask_wsgi(environ, start_response)
            except Exception:
                pass

    # 2. If request carries an X-Payment header, it's an x402-paying agent —
    #    let x402 middleware handle verification with facilitator fallback.
    if environ.get("HTTP_X_PAYMENT"):
        try:
            return _x402_wsgi(environ, start_response)
        except Exception:
            # Facilitator unreachable — return 503 with alternatives
            body = json.dumps({
                "error": "facilitator_unavailable",
                "message": "x402 payment facilitator is temporarily unreachable. Please try again or use alternative payment.",
                "alternatives": {
                    "stripe": "POST /buy-credits to purchase a prepaid API key via Stripe",
                    "api_key": "Use Bearer apk_xxx header with a prepaid API key",
                },
                "retry_after_seconds": 60,
            }).encode()
            start_response("503 Service Unavailable", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Retry-After", "60"),
                ("Access-Control-Allow-Origin", "*"),
            ])
            return [body]

    # If this route is not in the x402 routes dict, skip payment middleware entirely
    if not routes.get(route_key):
        return _raw_flask_wsgi(environ, start_response)

    # 3. No payment method provided — fall through to x402 middleware
    #    which returns a proper 402 with X-Payment-Info header that agents can pay.
    #    Intercept 402 responses to enrich with payment instructions.
    captured = {}

    def intercept_start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = headers
        return start_response(status, headers, exc_info)

    result = _x402_wsgi(environ, intercept_start_response)

    # Enrich 402 responses at WSGI level
    if captured.get("status", "").startswith("402"):
        try:
            path = environ.get("PATH_INFO", "")
            ip = environ.get("HTTP_CF_CONNECTING_IP", environ.get("REMOTE_ADDR", ""))
            funnel_log_event("402_shown", endpoint=path, ip=ip)
            enrichment = json.dumps({
                "endpoint": path,
                "payment_options": {
                    "api_key": {
                        "recommended": True,
                        "description": "Prepaid API key — fastest path to access.",
                        "how": "POST https://api.aipaygen.com/credits/buy with {\"amount_usd\": 5.0}",
                        "usage": f"Authorization: Bearer apk_YOUR_KEY",
                        "bulk_discount": "20% off when balance >= $2.00",
                    },
                    "x402_usdc": {
                        "description": "Pay per call with USDC on Base Mainnet via x402.",
                        "network": "Base Mainnet (eip155:8453)",
                    },
                    "mcp": {
                        "description": "10 free calls/day via MCP.",
                        "install": "pip install aipaygen-mcp",
                    },
                },
                "links": {
                    "buy_credits": "https://api.aipaygen.com/credits/buy",
                    "docs": "https://api.aipaygen.com/docs",
                    "discover": "https://api.aipaygen.com/discover",
                },
            }).encode()
            # Replace empty body with enriched one
            original = b"".join(result)
            if not original or original == b"{}":
                return [enrichment]
        except Exception:
            pass

    return result


app.wsgi_app = _api_key_wsgi

class _TrackedMessages:
    """Wraps anthropic.messages to auto-call track_cost() on every Claude API call."""
    def __init__(self, messages):
        self._messages = messages
    def create(self, *args, **kwargs):
        msg = self._messages.create(*args, **kwargs)
        try:
            endpoint = kwargs.get("_endpoint", "unknown")
            track_cost(endpoint, msg.model, msg.usage.input_tokens, msg.usage.output_tokens)
        except Exception:
            pass
        return msg

class _TrackedClaude:
    def __init__(self, client):
        self._client = client
        self.messages = _TrackedMessages(client.messages)
    def __getattr__(self, name):
        return getattr(self._client, name)

claude = _TrackedClaude(anthropic.Anthropic(api_key=ANTHROPIC_API_KEY))


def require_verified_agent(f):
    """Decorator: require JWT from a verified agent wallet."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ey"):
            try:
                payload = verify_jwt(auth[7:])
                request.agent = payload
                return f(*args, **kwargs)
            except Exception:
                pass
        return jsonify({"error": "Verified agent required. See /agents/challenge"}), 401
    return decorated


def _call_llm(messages, system="", max_tokens=1024, endpoint="unknown", model_override=None):
    """Route LLM call through model_router. Reads 'model' from request JSON if not overridden."""
    model_name = model_override or (request.get_json(silent=True) or {}).get("model", "claude-haiku")
    try:
        result = call_model(model_name, messages, system=system, max_tokens=max_tokens)
    except ModelNotFoundError as e:
        return None, str(e)
    # Track cost via discovery engine
    try:
        track_cost(endpoint, result["model_id"], result["input_tokens"], result["output_tokens"])
    except Exception:
        pass
    # Metered deduction if applicable
    api_key = request.environ.get("X_APIKEY_BYPASS", "")
    pricing_mode = request.environ.get("X_PRICING_MODE", "flat")
    if api_key and pricing_mode == "metered":
        cfg = get_model_config(model_name)
        # Per-request spend cap: reject if single call would cost > $1.00
        estimated_cost = (result["input_tokens"] * cfg["input_cost_per_m"] + result["output_tokens"] * cfg["output_cost_per_m"]) / 1_000_000
        if estimated_cost > 1.00:
            result["metered_warning"] = f"Request cost ${estimated_cost:.4f} exceeds $1.00 cap — deduction skipped"
        else:
            deduction = deduct_metered(
                api_key, result["input_tokens"], result["output_tokens"],
                cfg["input_cost_per_m"], cfg["output_cost_per_m"],
            )
            if deduction:
                result["metered_cost"] = deduction["cost"]
                result["balance_remaining"] = deduction["balance_remaining"]
                # Low balance warning
                if deduction["balance_remaining"] < 0.10:
                    result["metered_warning"] = f"Low balance: ${deduction['balance_remaining']:.4f} remaining"
    return result, None


init_db()
init_memory_db()
init_network_db()
init_keys_db()
init_jobs_db()
init_files_db()
init_webhooks_db()
init_referral_db()
init_discovery_db()
bootstrap_all_agents()

# Register all DB paths for weekly maintenance vacuum
import glob as _glob
_db_files = _glob.glob(os.path.join(os.path.dirname(__file__), "*.db"))
register_db_paths(_db_files)


# Scheduler now in scheduler.py — all jobs registered there
from scheduler import init_scheduler, get_scheduler
_scheduler = get_scheduler()
init_scheduler(
    claude_client=claude,
    call_model_fn=call_model,
    parse_json_fn=parse_json_from_claude,
    run_hourly_fn=run_hourly,
    run_daily_fn=run_daily,
    run_weekly_fn=run_weekly,
    run_canary_fn=run_canary,
    generate_blog_fn=generate_all_blog_posts,
    run_economy_fn=None,  # set below after _run_agent_economy is defined
)


# agent_response now in helpers.py (imported at top)


@app.before_request
def track_referral():
    ref = request.args.get("ref", request.headers.get("X-Referred-By", "")).strip()
    if ref and len(ref) <= 64 and _re.match(r'^[a-zA-Z0-9_\-]+$', ref):
        ip = _get_client_ip()
        ua = request.headers.get("User-Agent", "")
        try:
            record_click(ref, ip, request.path, ua)
        except Exception:
            pass
        # Also track scout conversions if ref matches scout pattern
        if "_" in ref and len(ref) <= 11:
            try:
                from discovery_scouts import record_scout_conversion
                record_scout_conversion(ref_code=ref, caller_ip=ip, user_agent=ua, endpoint=request.path)
            except Exception:
                pass


@app.before_request
def check_query_param_lengths():
    for key, value in request.args.items():
        if len(value) > 10000:
            return jsonify({"error": "param_too_long", "message": f"Query parameter '{key}' exceeds 10,000 character limit"}), 400


_ALLOWED_ORIGINS = {"https://aipaygen.com", "https://api.aipaygen.com", "https://mcp.aipaygen.com", "https://app.aipaygen.com"}

@app.after_request
def add_cors(response):
    import uuid
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        # Allow agent-to-agent calls (no browser origin) but block random browser origins
        response.headers["Access-Control-Allow-Origin"] = "https://aipaygen.com"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Payment, Authorization, Accept, X-Idempotency-Key"
    response.headers["Access-Control-Expose-Headers"] = "X-Request-ID, X-Payment-Info, X-Payment-Receipt"
    # Full UUID correlation ID per request
    req_id = request.headers.get("X-Idempotency-Key") or str(uuid.uuid4())
    response.headers["X-Request-ID"] = req_id
    # Payment receipt header on paid 2xx responses
    if request.headers.get("X-Payment") and 200 <= response.status_code < 300:
        response.headers["X-Payment-Receipt"] = f"paid:{req_id}"
    # Refund credit on 500 after payment
    if response.status_code >= 500 and request.headers.get("X-Payment"):
        route_key = f"{request.method} {request.path}"
        route_cfg = routes.get(route_key)
        if route_cfg:
            try:
                price_str = route_cfg.accepts[0].price
                amount = float(price_str.lstrip("$"))
                code = _issue_refund_credit(amount, request.path, req_id)
                response.headers["X-Refund-Credit"] = code
            except Exception:
                pass
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; object-src 'none'; frame-ancestors 'none'"
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    response.headers.pop("X-Powered-By", None)
    response.headers.pop("Server", None)
    return response


# ── Endpoint description lookup for 402 enrichment ───────────────────────────
_ENDPOINT_DESCRIPTIONS = {}  # populated lazily


def _get_endpoint_descriptions():
    """Build a flat dict of endpoint -> description from discover services."""
    global _ENDPOINT_DESCRIPTIONS
    if _ENDPOINT_DESCRIPTIONS:
        return _ENDPOINT_DESCRIPTIONS
    try:
        cats = _build_discover_services()
        for services in cats.values():
            for s in services:
                _ENDPOINT_DESCRIPTIONS[s["endpoint"]] = s["description"]
    except Exception:
        pass
    return _ENDPOINT_DESCRIPTIONS


@app.after_request
def enrich_402_response(response):
    """Enrich 402 Payment Required responses with helpful payment instructions."""
    if response.status_code != 402:
        return response
    try:
        caller_ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown")
        funnel_log_event("402_shown", endpoint=request.path, ip=caller_ip)
    except Exception:
        pass
    try:
        if response.content_type and "json" not in response.content_type:
            return response
        descs = _get_endpoint_descriptions()
        endpoint_desc = descs.get(request.path, f"AI-powered endpoint at {request.path}")
        import json as _json
        try:
            original = _json.loads(response.get_data(as_text=True))
        except Exception:
            original = {}
        enriched = {
            **original,
            "endpoint": request.path,
            "description": endpoint_desc,
            "payment_options": {
                "api_key": {
                    "recommended": True,
                    "description": "Prepaid API key — fastest path to access. Buy once, use everywhere.",
                    "how": "POST https://api.aipaygen.com/credits/buy with {\"amount_usd\": 5.0}",
                    "usage": f'curl -X POST https://api.aipaygen.com{request.path} -H "Authorization: Bearer apk_YOUR_KEY" -H "Content-Type: application/json" -d \'...\'',
                    "bulk_discount": "20% off all calls when balance >= $2.00",
                },
                "x402_usdc": {
                    "description": "Pay per call with USDC on Base Mainnet via x402 protocol.",
                    "how": "Include X-Payment header with signed USDC payment.",
                    "network": "Base Mainnet (eip155:8453)",
                    "docs": "https://x402.org",
                },
                "mcp": {
                    "description": "Use via MCP with 10 free calls/day.",
                    "install": "pip install aipaygen-mcp && claude mcp add aipaygen -- python -m aipaygen_mcp",
                    "sse": "https://mcp.aipaygen.com/mcp",
                },
            },
            "links": {
                "docs": "https://api.aipaygen.com/docs",
                "buy_credits": "https://api.aipaygen.com/credits/buy",
                "discover": "https://api.aipaygen.com/discover",
                "llms_txt": "https://api.aipaygen.com/llms.txt",
            },
        }
        response.set_data(_json.dumps(enriched))
        response.content_type = "application/json"
    except Exception:
        pass
    return response


# _api_error now in helpers.py (imported at top)


@app.errorhandler(400)
def bad_request(e):
    return _api_error(400, "bad_request", str(e))


@app.errorhandler(404)
def not_found(e):
    return _api_error(404, "not_found", "Endpoint not found. GET /discover for available endpoints.", discover="https://api.aipaygen.com/discover")


@app.errorhandler(405)
def method_not_allowed(e):
    return _api_error(405, "method_not_allowed", str(e))


@app.errorhandler(500)
def internal_error(e):
    return _api_error(500, "internal_server_error", "An error occurred processing your request. Please retry.", retry=True)


@app.route("/<path:path>", methods=["OPTIONS"])
def options(path):
    return "", 204


@app.route("/models", methods=["GET"])
def models_list():
    """List all available AI models with pricing."""
    return jsonify({"models": list_models(), "default": "claude-haiku"})


@app.route("/models/feedback", methods=["POST"])
def models_feedback():
    """Record quality feedback for a model+domain pair."""
    from model_router import record_outcome, get_all_outcomes
    data = request.get_json() or {}
    model = data.get("model", "")
    domain = data.get("domain", "general")
    score = float(data.get("quality_score", 0.5))
    if not model:
        return jsonify({"error": "model required"}), 400
    record_outcome(model, domain, score)
    return jsonify({"status": "recorded", "model": model, "domain": domain, "score": score})


@app.route("/models/outcomes", methods=["GET"])
def models_outcomes():
    """View outcome tracking stats for model auto-selection feedback."""
    from model_router import get_all_outcomes
    return jsonify({"outcomes": get_all_outcomes()})



# ── Skills DB + Search Engine (shared state for blueprints) ────────────────
_skills_db_path = os.path.join(os.path.dirname(__file__), "skills.db")
from skills_search import SkillsSearchEngine
_skills_engine = SkillsSearchEngine(_skills_db_path)
_discovery_jobs: dict = {}

# ── Blueprint Registration ─────────────────────────────────────────────────
from routes.ai_tools import ai_tools_bp
from routes.data import data_bp
from routes.streaming import streaming_bp
from routes.network import network_bp
from routes.auth import auth_bp
from routes.agent import agent_bp, init_agent_bp
from routes.marketplace import marketplace_bp, init_marketplace_bp
from routes.admin import admin_bp, init_admin_bp
from routes.skills import skills_bp, init_skills_bp, _init_skills_db
from routes.meta import meta_bp, init_meta_bp, _build_discover_services

# Initialize blueprints that need shared state
init_agent_bp(
    batch_handlers=None,  # set after ai_tools_bp is available
    skills_db_path=_skills_db_path,
    skills_engine=_skills_engine,
)
init_marketplace_bp(claude, _discovery_jobs)
init_admin_bp(claude, call_model, parse_json_from_claude)
init_skills_bp(_skills_db_path, _skills_engine)
init_meta_bp(_skills_db_path)
_init_skills_db()
_init_refund_db()

# Wire BATCH_HANDLERS from ai_tools into agent blueprint
from routes.ai_tools import BATCH_HANDLERS
from routes import agent as _agent_mod
_agent_mod._batch_handlers = BATCH_HANDLERS

app.register_blueprint(ai_tools_bp)
app.register_blueprint(data_bp)
app.register_blueprint(streaming_bp)
app.register_blueprint(network_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(agent_bp)
app.register_blueprint(marketplace_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(skills_bp)
app.register_blueprint(meta_bp)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
