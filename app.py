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
    get_rate_limit_info as _get_rate_limit_info,
    log_payment, parse_json_from_claude, agent_response,
    api_error as _api_error, require_admin, call_llm,
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
    check_and_use_free_tier, get_free_tier_status, get_free_tier_remaining,
    build_fingerprint, record_fingerprint, is_fingerprint_blocked,
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


# ── IP Abuse Detection (auto-ban after 10x 402 in 1 hour) ────────────────────
_banned_ips: dict = {}          # {ip: ban_expires_timestamp}
_402_tracker: dict = {}         # {ip: [timestamp, ...]}
_BAN_THRESHOLD = 10             # 402s in 1 hour triggers ban
_BAN_WINDOW = 3600              # 1 hour window for counting 402s
_BAN_DURATION = 86400           # 24 hour ban

def _track_402(ip: str):
    """Record a 402 hit for an IP and auto-ban if threshold exceeded."""
    now = _time.time()
    hits = [t for t in _402_tracker.get(ip, []) if t > now - _BAN_WINDOW]
    hits.append(now)
    _402_tracker[ip] = hits
    if len(hits) >= _BAN_THRESHOLD and ip not in _banned_ips:
        _banned_ips[ip] = now + _BAN_DURATION
        logging.getLogger(__name__).warning("AUTO-BANNED IP %s for 24h (%d x 402 in 1h)", ip, len(hits))
        try:
            funnel_log_event("ip_banned", ip=ip, metadata=json.dumps({
                "reason": "402_abuse", "count": len(hits), "ban_hours": 24,
            }))
        except Exception:
            pass

def _is_ip_banned(ip: str) -> bool:
    """Check if an IP is currently banned. Cleans up expired bans."""
    expires = _banned_ips.get(ip)
    if expires is None:
        return False
    if _time.time() >= expires:
        del _banned_ips[ip]
        return False
    return True


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
    with open(_key_path, "rb") as _f:
        _key = _f.read()
    with open(_env_enc, "rb") as _f:
        _data = Fernet(_key).decrypt(_f.read())
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
app.config["PREFERRED_URL_SCHEME"] = "https"
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB max request body
app.secret_key = os.getenv("ADMIN_SECRET") or os.urandom(32).hex()
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True

# ── Request-ID aware logging ───────────────────────────────────────────────
import logging as _logging


class _RequestIdFilter(_logging.Filter):
    """Inject request_id into every log record for correlation."""
    def filter(self, record):
        try:
            record.request_id = getattr(request, '_request_id', '-')
        except RuntimeError:
            record.request_id = '-'
        return True


_handler = _logging.StreamHandler()
_handler.setFormatter(_logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s'
))
_handler.addFilter(_RequestIdFilter())
app.logger.handlers = [_handler]
app.logger.setLevel(_logging.INFO)
# Also apply to the root logger so blueprint/module logs get request IDs
_logging.root.handlers = [_handler]
_logging.root.setLevel(_logging.INFO)

PAYMENTS_LOG = os.path.join(os.path.dirname(__file__), "payments.jsonl")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

import functools
import re as _re
# require_admin, _get_client_ip, log_payment now in helpers.py (imported at top)


# ── Refund credits table (for 500 errors after payment) ──────────────────────
_refund_db_path = os.path.join(os.path.dirname(__file__), "refunds.db")

def _init_refund_db():
    import sqlite3
    with sqlite3.connect(_refund_db_path) as conn:
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

def _issue_refund_credit(amount_usd: float, endpoint: str = "", request_id: str = "") -> str:
    """Issue a one-time credit code for a refund. Returns the code."""
    import sqlite3
    code = "refund_" + uuid.uuid4().hex[:12]
    with sqlite3.connect(_refund_db_path) as conn:
        conn.execute(
            "INSERT INTO refund_credits (code, amount_usd, endpoint, request_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (code, amount_usd, endpoint, request_id, datetime.utcnow().isoformat()),
        )
        conn.commit()
    return code

# ── Wallet Integrity Protection ──────────────────────────────────────────────
# The wallet address is hardcoded and verified at startup. It CANNOT be changed
# via environment variables alone — the checksum must match.
_VERIFIED_WALLET = "0x366D488a48de1B2773F3a21F1A6972715056Cb30"
_WALLET_CHECKSUM = "a3f7d2e1"  # first 8 chars of sha256 of the address
import hashlib as _hashlib
def _verify_wallet(addr: str) -> str:
    """Verify wallet address integrity. Rejects unauthorized changes."""
    expected_checksum = _hashlib.sha256(_VERIFIED_WALLET.lower().encode()).hexdigest()[:8]
    actual_checksum = _hashlib.sha256(addr.lower().encode()).hexdigest()[:8]
    if actual_checksum != expected_checksum:
        import logging
        logging.getLogger("wallet").critical(
            f"WALLET ADDRESS TAMPERED! Expected {_VERIFIED_WALLET}, got {addr}. Falling back to verified address."
        )
        return _VERIFIED_WALLET
    return addr

_env_wallet = os.getenv("WALLET_ADDRESS", _VERIFIED_WALLET)
WALLET_ADDRESS = _verify_wallet(_env_wallet)
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
    "POST /review-code": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Code review — quality, security, and performance analysis with actionable fixes ($0.05)",
    ),
    "POST /generate-docs": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate documentation for code — jsdoc, docstring, rustdoc ($0.03)",
    ),
    "POST /convert-code": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Convert code between programming languages ($0.03)",
    ),
    "POST /generate-api-spec": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate OpenAPI spec from natural language description ($0.05)",
    ),
    "POST /diff": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Analyze differences between two texts or code snippets ($0.02)",
    ),
    "POST /parse-csv": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Analyze CSV data and answer questions about it ($0.03)",
    ),
    "POST /cron": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate or explain cron expressions from natural language ($0.01)",
    ),
    "POST /changelog": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate changelog from commit messages ($0.02)",
    ),
    "POST /name-generator": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate product/company/feature names with taglines ($0.02)",
    ),
    "POST /privacy-check": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scan text for PII, secrets, and sensitive data ($0.02)",
    ),
    "POST /think": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.10", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Autonomous chain-of-thought reasoning — breaks down problems, calls tools, returns structured solution ($0.10)",
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
    "POST /memory/list": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="List all memory keys for an agent ($0.01)",
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
    "POST /session/start": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.001", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Start persistent agent session with shared context",
    ),
    "POST /workflow/run": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Run multi-step AI workflow — chain tools together with 15% discount",
    ),
    # ── Streaming endpoints (were unprotected — now gated) ────────────────────
    "POST /stream/research": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="text/event-stream",
        description="Streaming research — SSE events as Claude researches a topic ($0.02)",
    ),
    "POST /stream/write": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="text/event-stream",
        description="Streaming write — SSE events as Claude writes content ($0.02)",
    ),
    "POST /stream/analyze": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="text/event-stream",
        description="Streaming analysis — SSE events as Claude analyzes content ($0.02)",
    ),
    "POST /agent/stream": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.10", network=EVM_NETWORK)],
        mime_type="text/event-stream",
        description="Streaming autonomous agent — SSE events as agent reasons and acts ($0.10)",
    ),
}

_raw_flask_wsgi = app.wsgi_app  # save original Flask WSGI before x402 wraps it
payment_middleware(app, routes=routes, server=server)

# API key WSGI wrapper — intercepts Bearer apk_xxx before x402 checks
_x402_wsgi = app.wsgi_app


def _api_key_wsgi(environ, start_response):
    # Fix URL scheme/host for x402 402 headers (behind Cloudflare tunnel)
    if environ.get("HTTP_CF_CONNECTING_IP"):
        environ["wsgi.url_scheme"] = "https"
        environ["HTTP_HOST"] = "api.aipaygen.com"
        environ["SERVER_NAME"] = "api.aipaygen.com"
        environ["SERVER_PORT"] = "443"

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

    # 0. Banned IP check — auto-banned IPs get 429 immediately
    _ip = environ.get("HTTP_CF_CONNECTING_IP", environ.get("REMOTE_ADDR", "unknown"))
    if _is_ip_banned(_ip):
        body = json.dumps({
            "error": "ip_banned",
            "message": "Your IP has been temporarily blocked due to excessive requests. Try again later.",
            "retry_after_seconds": 3600,
        }).encode()
        start_response("429 Too Many Requests", [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("Retry-After", "3600"),
            ("Access-Control-Allow-Origin", "https://aipaygen.com"),
        ])
        return [body]

    # 0.1 Per-IP rate limit — tiered: 20/min unauthenticated, 120/min with API key
    if routes.get(route_key):
        try:
            is_authenticated = auth.startswith("Bearer apk_")
            _rate_limit = 120 if is_authenticated else 20
            if not _check_rate_limit(_ip, limit_override=_rate_limit):
                body = json.dumps({
                    "error": "rate_limited",
                    "message": f"Too many requests. Limit: {_rate_limit} per minute per IP.",
                    "retry_after_seconds": 60,
                    "upgrade": None if is_authenticated else "Authenticate with an API key for 120 req/min.",
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

    # 0.5 Free tier — 3 calls/day per IP before requiring payment
    #     Fingerprint tracking: detect IP rotation via VPN/proxy abuse.
    #     Only trust CF-Connecting-IP (set by Cloudflare, not spoofable by clients).
    #     X-Forwarded-For is NEVER used for billing decisions.
    if routes.get(route_key) and not auth.startswith("Bearer apk_") and not environ.get("HTTP_X_PAYMENT"):
        _ip = environ.get("HTTP_CF_CONNECTING_IP", environ.get("REMOTE_ADDR", "unknown"))

        # Build fingerprint from browser headers to detect IP rotation
        _fp = build_fingerprint(
            environ.get("HTTP_USER_AGENT", ""),
            environ.get("HTTP_ACCEPT_LANGUAGE", ""),
            environ.get("HTTP_ACCEPT_ENCODING", ""),
        )
        # Record fingerprint→IP mapping; returns False if fingerprint is blocked
        if not record_fingerprint(_ip, _fp):
            funnel_log_event("fingerprint_blocked", endpoint=environ.get("PATH_INFO", ""), ip=_ip, user_agent=environ.get("HTTP_USER_AGENT", ""))
            body = json.dumps({
                "error": "free_tier_blocked",
                "message": "Unusual activity detected from this client. Get an API key to continue.",
                "upgrade": {
                    "free_key": "POST https://aipaygen.com/auth/generate-key (includes $0.25 trial credits)",
                    "buy_credits": "https://aipaygen.com/buy-credits",
                },
            }).encode()
            start_response("402 Payment Required", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Access-Control-Allow-Origin", "*"),
            ])
            return [body]

        if check_and_use_free_tier(_ip):
            remaining = get_free_tier_remaining(_ip)
            environ["X_FREE_TIER"] = "1"
            environ["X_FREE_REMAINING"] = str(remaining)

            def _free_tier_start_response(status, headers, exc_info=None):
                headers = list(headers) + [("X-Free-Calls-Remaining", str(remaining))]
                if remaining <= 5:
                    headers.append(("X-Upgrade-Hint", "Get a free API key with $0.25 trial credits: POST https://api.aipaygen.com/auth/generate-key"))
                return start_response(status, headers, exc_info)

            return _raw_flask_wsgi(environ, _free_tier_start_response)
        else:
            funnel_log_event("free_tier_exhausted", endpoint=environ.get("PATH_INFO", ""), ip=_ip, user_agent=environ.get("HTTP_USER_AGENT", ""))
            _track_402(_ip)
            # Return 402 — free tier exhausted, must pay
            body = json.dumps({
                "error": "free_tier_exhausted",
                "message": "You've used all 3 free calls for today. Get an API key to continue.",
                "upgrade": {
                    "free_key": "POST https://aipaygen.com/auth/generate-key (includes $0.25 trial credits)",
                    "buy_credits": "https://aipaygen.com/buy-credits",
                    "pricing": "https://aipaygen.com/pricing",
                },
                "x402": "Or send USDC payment via X-Payment header",
            }).encode()
            start_response("402 Payment Required", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Access-Control-Allow-Origin", "*"),
                ("X-Upgrade-URL", "https://aipaygen.com/buy-credits"),
            ])
            return [body]

    # 1. Prepaid API key bypass (Bearer apk_xxx)
    if auth.startswith("Bearer apk_"):
        key = auth[7:]  # strip "Bearer "
        route_cfg = routes.get(route_key)
        pricing_mode = environ.get("HTTP_X_PRICING", "flat").lower()
        if route_cfg:
            try:
                if pricing_mode == "metered":
                    key_data = validate_key(key)
                    # For metered mode, validate key has minimum balance but do NOT
                    # deduct here — call_llm() handles metered deduction after the
                    # actual token count is known, preventing double-billing.
                    price_str = route_cfg.accepts[0].price
                    min_cost = float(price_str.lstrip("$"))
                    if key_data and key_data.get("balance_usd", 0) >= min_cost:
                        environ["X_APIKEY_BYPASS"] = key
                        environ["X_PRICING_MODE"] = "metered"
                        return _raw_flask_wsgi(environ, start_response)
                else:
                    # Flat: deduct fixed amount upfront (existing behavior)
                    price_str = route_cfg.accepts[0].price  # e.g. "$0.01"
                    cost = float(price_str.lstrip("$"))
                    key_data = validate_key(key)
                    if key_data:
                        # 20% bulk discount for prepaid keys with balance >= $2.00
                        if key_data.get("balance_usd", 0) >= 2.00:
                            cost = round(cost * 0.8, 4)
                        if deduct(key, cost):
                            environ["X_APIKEY_BYPASS"] = key
                            environ["X_PRICING_MODE"] = "flat"
                            return _raw_flask_wsgi(environ, start_response)
            except Exception as _key_err:
                logging.getLogger(__name__).error("API key auth failed: %s", _key_err)

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
        captured["headers"] = list(headers)
        captured["exc_info"] = exc_info
        # For 402s, delay start_response so we can add headers first
        if status.startswith("402"):
            return lambda s: None  # dummy write function
        return start_response(status, headers, exc_info)

    result = _x402_wsgi(environ, intercept_start_response)

    # Enrich 402 responses at WSGI level
    if captured.get("status", "").startswith("402"):
        try:
            path = environ.get("PATH_INFO", "")
            ip = environ.get("HTTP_CF_CONNECTING_IP", environ.get("REMOTE_ADDR", ""))
            funnel_log_event("402_shown", endpoint=path, ip=ip, user_agent=environ.get("HTTP_USER_AGENT", ""))
            _track_402(ip)
            remaining = get_free_tier_remaining(ip)
            # Get today's usage stats for personalized message
            try:
                from agent_network import _conn as _network_conn
                from datetime import datetime
                today = datetime.utcnow().strftime("%Y-%m-%d")
                with _network_conn() as nc:
                    row = nc.execute("SELECT calls_used FROM free_tier_usage WHERE ip=? AND date=?", (ip, today)).fetchone()
                    calls_today = row["calls_used"] if row else 0
            except Exception as _ft_err:
                logging.getLogger(__name__).error("Free tier lookup failed: %s", _ft_err)
                calls_today = 3
            # Add x402-standard headers + upgrade hints + discovery Link headers
            route_cfg_hdr = routes.get(route_key)
            try:
                price_hdr = route_cfg_hdr.accepts[0].price if route_cfg_hdr else "0"
            except (AttributeError, IndexError):
                price_hdr = "0"
            captured["headers"] = list(captured["headers"]) + [
                ("X-Free-Calls-Remaining", str(remaining)),
                ("X-Payment-Required", "true"),
                ("X-Price-USDC", price_hdr),
                ("X-Pay-To", WALLET_ADDRESS),
                ("X-Network", str(EVM_NETWORK)),
                ("X-Facilitator-URL", FACILITATOR_URL),
                ("Link", '</openapi.json>; rel="service-desc"'),
                ("Link", '</.well-known/ai-plugin.json>; rel="ai-plugin"'),
                ("Link", '</.well-known/x402>; rel="payment-requirements"'),
                ("Link", '</discover>; rel="discovery"'),
            ]
            if remaining == 0:
                captured["headers"].append(("X-Upgrade-Hint", "Buy API key at https://aipaygen.com/buy-credits or fund with crypto at https://aipaygen.com/crypto"))
            route_cfg = routes.get(route_key)
            price = route_cfg.accepts[0].price if route_cfg else "varies"
            enrichment = json.dumps({
                "error": "payment_required",
                "message": f"Free tier exhausted ({calls_today}/{3} calls used today). Get unlimited access starting at $1.",
                "endpoint": path,
                "price": price,
                "unlock": {
                    "1_get_free_key": {
                        "description": "Generate a free API key with $0.25 trial credits (~40 calls). No payment needed.",
                        "command": "curl -X POST https://api.aipaygen.com/auth/generate-key -H 'Content-Type: application/json' -d '{\"label\": \"my-key\"}'",
                    },
                    "2_use_key": {
                        "description": "Add the key to your requests.",
                        "header": "Authorization: Bearer apk_YOUR_KEY",
                        "example": f"curl -X POST https://api.aipaygen.com{path} -H 'Authorization: Bearer apk_YOUR_KEY' -H 'Content-Type: application/json' -d '...'",
                    },
                    "3_buy_more": {
                        "description": "Need more? Add credits from $1.",
                        "url": "https://aipaygen.com/buy-credits",
                        "tiers": {"$1": "~166 AI calls", "$5": "~830 calls + 20% bulk discount", "$20": "~4,000 calls"},
                    },
                },
                "also_accepted": {
                    "x402_usdc": {
                        "description": "Pay per call with USDC (no signup). Base, Solana, or Stellar.",
                        "header": "X-Payment",
                        "docs": "https://x402.org",
                    },
                },
                "links": {
                    "buy_credits": "https://aipaygen.com/buy-credits",
                    "docs": "https://aipaygen.com/docs",
                    "pricing": "https://aipaygen.com/pricing",
                },
            }).encode()
            # Replace empty body with enriched one
            original = b"".join(result)
            if not original or original == b"{}":
                body = enrichment
            else:
                body = original
            # Now send the 402 response with enriched headers
            captured["headers"].append(("Content-Length", str(len(body))))
            start_response(captured["status"], captured["headers"], captured.get("exc_info"))
            return [body]
        except Exception:
            # Fallback: send original 402 without enrichment
            start_response(captured["status"], captured["headers"], captured.get("exc_info"))
            pass

    # For 402s that hit the exception path, result may already be consumed
    if captured.get("status", "").startswith("402"):
        return result

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


init_db()
init_memory_db()
init_network_db()
init_keys_db()
init_jobs_db()
init_files_db()
init_webhooks_db()
from webhook_dispatch import init_webhooks_dispatch_db
init_webhooks_dispatch_db()
init_referral_db()
init_discovery_db()
from accounts import init_accounts_db
init_accounts_db()
bootstrap_all_agents()

# Register all DB paths for weekly maintenance vacuum
import glob as _glob
_db_files = _glob.glob(os.path.join(os.path.dirname(__file__), "*.db"))
register_db_paths(_db_files)

# Enable WAL mode on all SQLite databases for better concurrent read performance
import sqlite3 as _sqlite3
for _dbf in _db_files:
    try:
        _wc = _sqlite3.connect(_dbf)
        _wc.execute("PRAGMA journal_mode=WAL")
        _wc.close()
    except Exception:
        pass

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


# ── Response time tracking ──────────────────────────────────────────────────────
import collections as _collections

# Ring buffer: stores (timestamp, endpoint, response_time_ms) for last hour
_response_times = _collections.deque(maxlen=5000)

@app.before_request
def _start_timer():
    request._start_time = _time.time()


@app.before_request
def _assign_request_id():
    """Generate a unique request ID for every request (used in headers, logs, errors)."""
    req_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request._request_id = req_id


@app.after_request
def _record_response_time(response):
    start = getattr(request, '_start_time', None)
    if start is not None:
        elapsed_ms = round((_time.time() - start) * 1000, 1)
        # Only track API endpoints (skip static, health)
        path = request.path
        if path not in ("/health", "/favicon.ico") and not path.startswith("/static"):
            _response_times.append((_time.time(), path, elapsed_ms))
    return response


def get_response_time_stats(window_seconds=3600):
    """Return response time stats for the given window. Used by /status page."""
    cutoff = _time.time() - window_seconds
    times = [ms for ts, _, ms in _response_times if ts >= cutoff]
    if not times:
        return {"avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "count": 0}
    times.sort()
    n = len(times)
    return {
        "avg_ms": round(sum(times) / n, 1),
        "p50_ms": round(times[n // 2], 1),
        "p95_ms": round(times[int(n * 0.95)], 1),
        "p99_ms": round(times[int(n * 0.99)], 1),
        "count": n,
    }


def get_endpoint_response_times(window_seconds=3600, top_n=10):
    """Return per-endpoint average response times. Used by /status page."""
    cutoff = _time.time() - window_seconds
    by_endpoint = {}
    for ts, path, ms in _response_times:
        if ts >= cutoff:
            if path not in by_endpoint:
                by_endpoint[path] = []
            by_endpoint[path].append(ms)
    result = []
    for path, times in by_endpoint.items():
        result.append({
            "endpoint": path,
            "avg_ms": round(sum(times) / len(times), 1),
            "calls": len(times),
        })
    result.sort(key=lambda x: x["calls"], reverse=True)
    return result[:top_n]


# ── Graceful Degradation: Maintenance Mode + DB Retry ────────────────────────
from circuit_breaker import (
    is_maintenance_mode as _is_maintenance,
    get_maintenance_retry_after as _get_retry_after,
    set_maintenance_mode as _set_maintenance,
    db_execute_with_retry,  # noqa: F401 — exported for use by routes
    all_providers_down as _all_providers_down,
    get_model_fallback_response as _get_fallback,
)

# Endpoints exempt from maintenance mode
_MAINTENANCE_EXEMPT = frozenset(["/health", "/health/deep", "/status", "/api/uptime"])


@app.before_request
def check_maintenance_mode():
    """Return 503 with Retry-After if maintenance mode is active."""
    if _is_maintenance() and request.path not in _MAINTENANCE_EXEMPT:
        retry = _get_retry_after()
        return jsonify({
            "error": "maintenance",
            "message": "Service is undergoing scheduled maintenance. Please retry later.",
            "retry_after_seconds": retry,
        }), 503, {"Retry-After": str(retry)}


@app.route("/admin/maintenance", methods=["POST"])
@require_admin
def toggle_maintenance():
    """Toggle maintenance mode. POST {"enabled": true/false, "retry_after": 300}"""
    data = request.get_json() or {}
    enabled = data.get("enabled", False)
    retry = min(max(int(data.get("retry_after", 300)), 60), 86400)
    _set_maintenance(enabled, retry)
    return jsonify({"maintenance_mode": enabled, "retry_after": retry})


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


# ── Gzip compression ────────────────────────────────────────────────────────────

import gzip as _gzip
import io as _io

_GZIP_MIN_SIZE = 500  # Only compress responses larger than 500 bytes

@app.after_request
def gzip_response(response):
    """Compress responses with gzip if the client supports it."""
    if (response.status_code < 200 or response.status_code >= 300
            or response.direct_passthrough
            or "Content-Encoding" in response.headers
            or "gzip" not in request.headers.get("Accept-Encoding", "")):
        return response
    content_type = response.content_type or ""
    if not any(ct in content_type for ct in ("text/", "application/json", "application/javascript", "image/svg")):
        return response
    data = response.get_data()
    if len(data) < _GZIP_MIN_SIZE:
        return response
    buf = _io.BytesIO()
    with _gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as f:
        f.write(data)
    compressed = buf.getvalue()
    if len(compressed) >= len(data):
        return response
    response.set_data(compressed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = len(compressed)
    response.headers["Vary"] = "Accept-Encoding"
    return response


# ── Cache-Control headers for specific routes ──────────────────────────────────

_CACHE_PUBLIC_1H = frozenset({"/pricing", "/docs", "/discover", "/docs/api", "/sell", "/sdk"})
_CACHE_NO_CACHE = frozenset({"/health", "/status"})

@app.after_request
def set_cache_headers(response):
    """Set Cache-Control for static-ish pages. Dynamic/API routes keep default no-store."""
    path = request.path
    if path in _CACHE_PUBLIC_1H:
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif path in _CACHE_NO_CACHE:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=604800"
    return response


_ALLOWED_ORIGINS = {"https://aipaygen.com", "https://api.aipaygen.com", "https://mcp.aipaygen.com", "https://app.aipaygen.com"}

@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        # Allow agent-to-agent calls (no browser origin) but block random browser origins
        response.headers["Access-Control-Allow-Origin"] = "https://aipaygen.com"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Payment, Authorization, Accept, X-Idempotency-Key, X-Request-Id"
    response.headers["Access-Control-Expose-Headers"] = (
        "X-Request-Id, X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, "
        "X-API-Version, X-Powered-By, "
        "X-Payment-Info, X-Payment-Receipt, X-Free-Calls-Remaining, X-Upgrade-Hint, "
        "X-Payment-Required, X-Price-USDC, X-Pay-To, X-Network, X-Facilitator-URL, "
        "Deprecation, Sunset, Link"
    )

    # ── Request ID (use pre-generated from before_request, or idempotency key) ──
    req_id = getattr(request, '_request_id', None) or str(uuid.uuid4())
    if request.headers.get("X-Idempotency-Key"):
        req_id = request.headers["X-Idempotency-Key"]
    response.headers["X-Request-Id"] = req_id

    # ── API Version + Powered-By ───────────────────────────────────────────────
    response.headers["X-API-Version"] = "1.9.0"
    response.headers["X-Powered-By"] = "AiPayGen"

    # ── Rate Limit Headers ─────────────────────────────────────────────────────
    try:
        ip = _get_client_ip()
        rl = _get_rate_limit_info(ip)
        response.headers["X-RateLimit-Limit"] = str(rl["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rl["remaining"])
        response.headers["X-RateLimit-Reset"] = str(rl["reset"])
    except Exception:
        pass

    # ── Deprecation headers for legacy duplicate routes ────────────────────────
    _deprecated = {
        "/free/joke": "/data/joke",
        "/free/quote": "/data/quote",
    }
    canonical = _deprecated.get(request.path)
    if canonical:
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = "2026-09-01T00:00:00Z"
        response.headers["Link"] = f'<https://api.aipaygen.com{canonical}>; rel="successor-version"'

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
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # CSP: full policy for HTML pages, relaxed for JSON API responses
    content_type = response.content_type or ""
    if "text/html" in content_type:
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; object-src 'none'; frame-ancestors 'none'"
    elif "json" in content_type:
        response.headers["Content-Security-Policy"] = "default-src 'none'"
    else:
        response.headers["Content-Security-Policy"] = "default-src 'self'"
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    response.headers.pop("Server", None)
    return response


# ── Free tier upsell injection ─────────────────────────────────────────────────

@app.after_request
def inject_free_tier_upsell(response):
    """Add upgrade CTA to free tier JSON responses so users know how to get a key."""
    if response.status_code != 200:
        return response
    remaining_str = request.environ.get("X_FREE_REMAINING")
    if not remaining_str:
        return response
    try:
        remaining_int = int(remaining_str)
    except (ValueError, TypeError):
        return response
    if not response.content_type or "json" not in response.content_type:
        return response
    try:
        import json as _json
        data = _json.loads(response.get_data(as_text=True))
        if not isinstance(data, dict):
            return response
        data["_free_tier"] = {
            "calls_remaining": remaining_int,
            "total_daily": 10,
        }
        if remaining_int <= 5:
            data["_free_tier"]["upgrade"] = {
                "message": f"Only {remaining_int} free calls left today. Get a free API key with $0.25 trial credits (~40 calls).",
                "get_key": "POST https://api.aipaygen.com/auth/generate-key",
                "quick_buy_url": "https://aipaygen.com/buy-credits?amount=5&quick=1",
                "buy_credits": "https://aipaygen.com/buy-credits",
            }
        response.set_data(_json.dumps(data))
    except Exception:
        pass
    return response


# ── Endpoint description lookup for 402 enrichment ───────────────────────────
_ENDPOINT_DESC_LOCK = threading.Lock()
_ENDPOINT_DESCRIPTIONS = {}  # populated lazily


def _get_endpoint_descriptions():
    """Build a flat dict of endpoint -> description from discover services."""
    global _ENDPOINT_DESCRIPTIONS
    if _ENDPOINT_DESCRIPTIONS:
        return _ENDPOINT_DESCRIPTIONS
    with _ENDPOINT_DESC_LOCK:
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
        funnel_log_event("402_shown", endpoint=request.path, ip=caller_ip, user_agent=request.headers.get("User-Agent", ""))
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
            "error": "payment_required",
            "message": f"Free tier exhausted. Get unlimited access starting at $1.",
            "endpoint": request.path,
            "description": endpoint_desc,
            "unlock": {
                "1_get_free_key": {
                    "description": "Generate a free API key with $0.25 trial credits (~40 calls). No payment needed.",
                    "command": "curl -X POST https://api.aipaygen.com/auth/generate-key -H 'Content-Type: application/json' -d '{\"label\": \"my-key\"}'",
                },
                "2_use_key": {
                    "description": "Add the key to your requests.",
                    "header": "Authorization: Bearer apk_YOUR_KEY",
                },
                "3_buy_more": {
                    "description": "Need more? Add credits from $1.",
                    "url": "https://aipaygen.com/buy-credits",
                },
            },
            "quick_buy_url": "https://aipaygen.com/buy-credits?amount=5&quick=1",
            "also_accepted": {
                "x402_usdc": {"description": "Pay per call with USDC. No signup.", "docs": "https://x402.org"},
                "mcp": {"description": "Install MCP package for 3 free calls/day.", "install": "pip install aipaygen-mcp"},
            },
            "quick_buy_url": "https://aipaygen.com/buy-credits?amount=5&quick=1",
            "try_free": f"https://aipaygen.com/try?tool={request.path.strip('/')}",
            "links": {
                "quick_buy": "https://aipaygen.com/buy-credits?amount=5&quick=1",
                "buy_credits": "https://aipaygen.com/buy-credits",
                "quick_buy_5": "https://aipaygen.com/buy-credits?amount=5&quick=1",
                "quick_buy_1": "https://aipaygen.com/buy-credits?amount=1&quick=1",
                "pricing": "https://aipaygen.com/pricing",
                "try_demo": f"https://aipaygen.com/try?tool={request.path.strip('/')}",
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
    app.logger.debug("400 error: %s", e)
    return _api_error(400, "bad_request", "Bad request")


_COMMON_MISSPELLINGS = {
    "dicovery": "/discover", "disover": "/discover", "discovr": "/discover",
    "documention": "/docs", "doc": "/docs", "documentation": "/docs",
    "priceing": "/pricing", "prices": "/pricing", "price": "/pricing",
    "healthcheck": "/health", "heatlh": "/health",
    "tryit": "/try", "demo": "/try", "playground": "/playground",
    "api": "/docs/api", "swagger": "/docs/api", "openapi": "/openapi.json",
    "staus": "/status", "statsu": "/status",
    "catalog": "/discover", "tools": "/discover",
    "signin": "/buy-credits", "login": "/buy-credits", "signup": "/buy-credits",
}


@app.errorhandler(404)
def not_found(e):
    path = request.path.strip("/").lower()
    suggestion = _COMMON_MISSPELLINGS.get(path)
    suggested_pages = [
        {"name": "Try Tools", "url": "https://aipaygen.com/try"},
        {"name": "Documentation", "url": "https://aipaygen.com/docs"},
        {"name": "Pricing", "url": "https://aipaygen.com/pricing"},
        {"name": "Discover", "url": "https://aipaygen.com/discover"},
    ]
    if request.accept_mimetypes.best == 'text/html':
        hint = f'<p>Did you mean <a href="{suggestion}">{suggestion}</a>?</p>' if suggestion else ""
        links = "".join(f'<li><a href="{p["url"]}">{p["name"]}</a></li>' for p in suggested_pages)
        html = f"""<!DOCTYPE html><html><head><title>404 — Not Found</title>
<style>body{{font-family:sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.box{{text-align:center;max-width:480px;padding:40px}}h1{{color:#f85149;font-size:3rem}}a{{color:#58a6ff}}</style></head>
<body><div class="box"><h1>404</h1><p>This page does not exist.</p>{hint}<h3>Try these instead:</h3><ul style="list-style:none;padding:0">{links}</ul>
<p style="margin-top:24px;color:#8b949e"><a href="/">Back to home</a></p></div></body></html>"""
        return html, 404
    req_id = getattr(request, '_request_id', None)
    resp = {
        "error": "not_found",
        "message": "The requested endpoint does not exist.",
        "request_id": req_id,
        "discover": "https://api.aipaygen.com/discover",
        "suggested_pages": suggested_pages,
    }
    if suggestion:
        resp["did_you_mean"] = suggestion
    return jsonify(resp), 404


@app.errorhandler(405)
def method_not_allowed(e):
    req_id = getattr(request, '_request_id', None)
    return jsonify({"error": "method_not_allowed", "message": "This HTTP method is not supported for this endpoint.", "request_id": req_id, "docs": "https://aipaygen.com/docs"}), 405


@app.errorhandler(415)
def unsupported_media_type(e):
    req_id = getattr(request, '_request_id', None)
    return jsonify({"error": "unsupported_media_type", "message": "Content-Type must be application/json for POST requests.", "request_id": req_id, "docs": "https://aipaygen.com/docs#quickstart"}), 415


@app.errorhandler(429)
def rate_limited(e):
    req_id = getattr(request, '_request_id', None)
    return jsonify({"error": "rate_limited", "message": "Rate limit exceeded. Upgrade to a paid plan for higher limits.", "request_id": req_id, "pricing": "https://aipaygen.com/pricing", "buy_credits": "https://aipaygen.com/buy-credits"}), 429


@app.errorhandler(500)
def internal_error(e):
    req_id = getattr(request, '_request_id', None)
    if request.accept_mimetypes.best == 'text/html':
        html = f"""<!DOCTYPE html><html><head><title>500 — Server Error</title>
<style>body{{font-family:sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.box{{text-align:center;max-width:480px;padding:40px}}h1{{color:#f85149;font-size:3rem}}a{{color:#58a6ff}}.rid{{font-family:monospace;color:#8b949e;font-size:0.8rem}}</style></head>
<body><div class="box"><h1>500</h1><p>Something went wrong on our end.</p>
<p>Check <a href="/status">service status</a> for live health info.</p>
<p class="rid">Request ID: {req_id}</p>
<p style="margin-top:24px;color:#8b949e"><a href="/">Back to home</a></p></div></body></html>"""
        return html, 500
    return jsonify({
        "error": "internal_server_error",
        "message": "An unexpected error occurred.",
        "request_id": req_id,
        "status_page": "https://aipaygen.com/status",
        "health": "https://aipaygen.com/health",
    }), 500


@app.before_request
def handle_options_preflight():
    """Handle CORS preflight requests globally without a catch-all route."""
    if request.method == "OPTIONS":
        return "", 204


# ── Bot / Scanner Filtering ──────────────────────────────────────────────────

_SCANNER_PATHS = frozenset([
    "/wp-admin", "/wp-login.php", "/wp-content", "/wordpress",
    "/.git/config", "/.env", "/.htaccess", "/phpinfo.php",
    "/admin/config", "/cgi-bin", "/wp-includes",
    "/xmlrpc.php", "/wp-cron.php", "/wp-json/wp",
])

_BOT_UA_SUBSTRINGS = [
    "SparixEmailScraper", "CMS-Checker", "zgrab", "masscan",
    "nuclei", "sqlmap", "nikto", "dirbuster", "gobuster",
    "wpscan", "nmap", "scaninfo", "censys",
]


@app.before_request
def block_scanners():
    """Block known vulnerability scanners and path probes."""
    path = request.path.lower()
    # Block WordPress / common scanner paths
    for p in _SCANNER_PATHS:
        if path.startswith(p.lower()):
            return "", 403
    # Block known scanner user agents
    ua = request.headers.get("User-Agent", "")
    ua_lower = ua.lower()
    for bot in _BOT_UA_SUBSTRINGS:
        if bot.lower() in ua_lower:
            return "", 403


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

# Agent Builder
from routes.builder import builder_bp, init_builder_bp, init_builder_db
init_builder_db()
init_builder_bp(_skills_db_path, _skills_engine, BATCH_HANDLERS)
app.register_blueprint(builder_bp)

# Sessions
from routes.sessions import sessions_bp, init_sessions_bp
init_sessions_bp(BATCH_HANDLERS)
app.register_blueprint(sessions_bp)

# Workflow Engine
from routes.workflow import workflow_bp
app.register_blueprint(workflow_bp)

# Accounts
from routes.accounts import accounts_bp
app.register_blueprint(accounts_bp)

# Discovery (x402 catalog, pricing, compare, wallet analytics)
from routes.discovery import discovery_bp, init_discovery
init_discovery(routes)
app.register_blueprint(discovery_bp)

# Utility (API Toll-style tools — geocode, whois, NLP, finance, security, math, transforms)
from routes.utility import utility_bp
app.register_blueprint(utility_bp)

# Seller marketplace
from routes.seller import seller_bp
app.register_blueprint(seller_bp)

# Webhook testing UI
from routes.webhooks import webhooks_bp
app.register_blueprint(webhooks_bp)

# Crypto deposits
from routes.crypto import crypto_bp
from crypto_deposits import init_crypto_db
init_crypto_db()
app.register_blueprint(crypto_bp)

# Start crypto deposit poller (background thread)
from crypto_poller import start_poller as _start_crypto_poller
_start_crypto_poller(WALLET_ADDRESS)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
