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

from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync, PaymentOption
from x402.http.middleware.flask import payment_middleware
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServerSync
from web import scrape_url, search_web
from api_catalog import init_db, get_all_apis, get_api, get_recent_runs
from api_discovery import run_all_agents
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

# ── TTL response cache (free data + Claude responses) ────────────────────────
_ttl_cache: dict = {}

def _cache_get(key: str):
    entry = _ttl_cache.get(key)
    if entry and _time.time() < entry[1]:
        return entry[0]
    return None

def _cache_set(key: str, data, ttl: int):
    _ttl_cache[key] = (data, _time.time() + ttl)


# ── Per-IP Rate Limiter (60 req/min on AI endpoints) ─────────────────────────
_ip_rate: dict = {}  # ip -> [timestamps]
_RATE_LIMIT = 60
_RATE_WINDOW = 60  # seconds

def _check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    now = _time.time()
    window_start = now - _RATE_WINDOW
    times = _ip_rate.get(ip, [])
    times = [t for t in times if t > window_start]
    if len(times) >= _RATE_LIMIT:
        _ip_rate[ip] = times
        return False
    times.append(now)
    _ip_rate[ip] = times
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
    _key = open(_key_path, "rb").read()
    _data = Fernet(_key).decrypt(open(_env_enc, "rb").read())
    with tempfile.NamedTemporaryFile(delete=False, suffix=".env") as _tmp:
        _tmp.write(_data)
        _tmp_path = _tmp.name
    load_dotenv(_tmp_path)
    os.unlink(_tmp_path)
    # Also load plain .env for any additional keys (won't override encrypted ones)
    if os.path.exists(_env_plain):
        load_dotenv(_env_plain, override=False)
else:
    load_dotenv(_env_plain)

app = Flask(__name__)

PAYMENTS_LOG = os.path.join(os.path.dirname(__file__), "payments.jsonl")

def log_payment(endpoint, amount_usd, caller_ip):
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "endpoint": endpoint,
        "amount_usd": amount_usd,
        "ip": caller_ip,
    }
    with open(PAYMENTS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x366D488a48de1B2773F3a21F1A6972715056Cb30")
EVM_NETWORK: Network = "eip155:8453"  # Base Mainnet
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://api.cdp.coinbase.com/platform/v2/x402")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://api.aipaygent.xyz")

import stripe as _stripe
if STRIPE_SECRET_KEY:
    _stripe.api_key = STRIPE_SECRET_KEY

CDP_API_KEY_ID = os.getenv("CDP_API_KEY_ID", "")
CDP_API_KEY_SECRET = os.getenv("CDP_API_KEY_SECRET", "")

def _cdp_create_headers():
    """Generate CDP JWT auth headers for x402 facilitator endpoints."""
    from cdp.auth import get_auth_headers, GetAuthHeadersOptions
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

if CDP_API_KEY_ID and CDP_API_KEY_SECRET:
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
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.15", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Deep research: search + scrape + Claude synthesis with citations ($0.15)",
    ),
    "POST /write": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude writes content (article, post, copy) to your spec ($0.05)",
    ),
    "POST /analyze": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude analyzes data or text and returns structured insights ($0.02)",
    ),
    "POST /code": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude generates code from a description in any language ($0.05)",
    ),
    "POST /summarize": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude summarizes long text or articles into key points ($0.01)",
    ),
    "POST /translate": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude translates text to any language ($0.02)",
    ),
    "POST /social": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Claude generates platform-optimized social media posts ($0.03)",
    ),
    "POST /batch": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.10", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Run up to 5 AI operations in one payment — research, write, analyze, translate, social, code ($0.10)",
    ),
    "POST /extract": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract structured data from any text using a schema you define ($0.02)",
    ),
    "POST /qa": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Answer a question given a context document — core RAG building block ($0.02)",
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
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Compare two texts — similarities, differences, recommendation ($0.02)",
    ),
    "POST /transform": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Transform text with any instruction — rewrite, reformat, clean, expand, condense ($0.02)",
    ),
    "POST /chat": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Stateless multi-turn chat — send message history, get Claude's reply ($0.03)",
    ),
    "POST /plan": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate a step-by-step action plan for any goal ($0.03)",
    ),
    "POST /decide": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Decision framework — pros/cons, risks, and a recommendation ($0.03)",
    ),
    "POST /proofread": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Grammar, spelling, clarity corrections with tracked changes ($0.02)",
    ),
    "POST /explain": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Explain any concept at beginner, intermediate, or expert level ($0.02)",
    ),
    "POST /questions": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate interview, FAQ, or quiz questions from any content ($0.02)",
    ),
    "POST /outline": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate a structured hierarchical outline from a topic or document ($0.02)",
    ),
    "POST /email": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Compose professional emails — subject, body, tone, length ($0.03)",
    ),
    "POST /sql": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Natural language to SQL — describe what you want, get a query ($0.05)",
    ),
    "POST /regex": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate regex patterns from plain English description ($0.02)",
    ),
    "POST /mock": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate realistic mock data — JSON, CSV, or plain list ($0.03)",
    ),
    "POST /score": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Score content quality on any custom rubric — returns per-criterion scores ($0.02)",
    ),
    "POST /timeline": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract or generate a chronological timeline of events from text ($0.02)",
    ),
    "POST /action": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract action items, tasks, and owners from meeting notes or text ($0.01)",
    ),
    "POST /pitch": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate elevator pitch — hook, value prop, call to action ($0.03)",
    ),
    "POST /debate": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Arguments for and against any position with strength ratings ($0.03)",
    ),
    "POST /headline": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate compelling headlines and titles for any content ($0.01)",
    ),
    "POST /fact": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Extract factual claims from text with source hints and verifiability scores ($0.02)",
    ),
    "POST /rewrite": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Rewrite text for a specific audience, reading level, or brand voice ($0.02)",
    ),
    "POST /tag": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Auto-tag content using a provided taxonomy or free-form tagging ($0.01)",
    ),
    "POST /pipeline": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.15", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Chain up to 5 operations where each step can use the previous output ($0.15)",
    ),
    "POST /api-call": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Proxy HTTP call to any cataloged API with optional Claude enrichment ($0.05)",
    ),
    "POST /scrape/google-maps": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.10", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape Google Maps places for any query — names, addresses, ratings ($0.10)",
    ),
    "POST /scrape/instagram": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape Instagram profile posts and metadata ($0.05)",
    ),
    "POST /scrape/tweets": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape tweets by search query or hashtag ($0.05)",
    ),
    "POST /scrape/linkedin": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.15", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape LinkedIn profile data ($0.15)",
    ),
    "POST /scrape/youtube": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape YouTube video metadata by search keyword ($0.05)",
    ),
    "POST /scrape/web": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Crawl any website and extract structured content ($0.05)",
    ),
    "POST /scrape/tiktok": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape TikTok profile videos and metadata ($0.05)",
    ),
    "POST /scrape/facebook-ads": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.10", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Scrape Facebook Ad Library for any brand or keyword ($0.10)",
    ),
    "POST /scrape/actor": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.10", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Run any Apify actor by ID with custom input ($0.10)",
    ),
    "POST /vision": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Analyze any image URL with Claude Vision — describe, extract, or answer questions ($0.05)",
    ),
    "POST /rag": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Mini RAG — provide documents + query, get a grounded answer with citations ($0.05)",
    ),
    "POST /diagram": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate Mermaid diagrams (flowchart, sequence, erd, gantt, mindmap) from description ($0.03)",
    ),
    "POST /json-schema": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate JSON Schema (draft-07) from a plain English description ($0.02)",
    ),
    "POST /test-cases": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.03", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Generate comprehensive test cases for code or a feature description ($0.03)",
    ),
    "POST /workflow": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.20", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Multi-step agentic reasoning — Claude Sonnet breaks down and executes complex goals ($0.20)",
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
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Search all memories for an agent by keyword — returns ranked matches ($0.02)",
    ),
    "POST /memory/clear": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Delete all memories for an agent_id ($0.01)",
    ),
    "POST /chain": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.25", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Chain up to 5 AI endpoints in sequence — each step can reference prior results ($0.25)",
    ),
    "POST /marketplace/call": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Proxy-call any agent marketplace listing — we handle routing + payment ($0.05 + listing price)",
    ),
    "POST /message/send": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.01", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Send a direct message from one agent to another ($0.01)",
    ),
    "POST /message/broadcast": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Broadcast a message to all agents in the network ($0.02)",
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
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Execute Python code in a sandboxed subprocess, returns stdout/stderr ($0.05)",
    ),
    "GET /web/search": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.02", network=EVM_NETWORK)],
        mime_type="application/json",
        description="DuckDuckGo web search — instant answers + related results ($0.02)",
    ),
    "POST /enrich": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$0.05", network=EVM_NETWORK)],
        mime_type="application/json",
        description="Entity enrichment — aggregate data about an IP, crypto, country, or company ($0.05)",
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

    # 0. Per-IP rate limit (60 req/min) — applied to AI route calls only
    if routes.get(route_key):
        try:
            _ip = (
                environ.get("HTTP_X_FORWARDED_FOR", environ.get("REMOTE_ADDR", "unknown"))
                .split(",")[0].strip()
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
                    ("Access-Control-Allow-Origin", "*"),
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
                    if key_data and key_data.get("balance_usd", 0) >= cost and deduct(key, cost):
                        environ["X_APIKEY_BYPASS"] = key
                        environ["X_PRICING_MODE"] = "flat"
                        return _raw_flask_wsgi(environ, start_response)
            except Exception:
                pass

    # 2. Free daily tier bypass — 10 free AI calls/day per IP (no payment needed)
    route_cfg = routes.get(route_key)
    if route_cfg:
        try:
            ip = (
                environ.get("HTTP_X_FORWARDED_FOR", environ.get("REMOTE_ADDR", "unknown"))
                .split(",")[0].strip()
            )
            if check_and_use_free_tier(ip):
                environ["X_FREE_TIER_BYPASS"] = "1"
                return _raw_flask_wsgi(environ, start_response)
            else:
                # Free tier exhausted — return smart conversion nudge instead of raw 402
                status = get_free_tier_status(ip)
                nudge = json.dumps({
                    "error": "free_tier_exhausted",
                    "message": f"You've used all {status['daily_limit']} free calls for today.",
                    "resets_at": "midnight UTC",
                    "upgrade": {
                        "option_1": {
                            "label": "Get a $5 starter key (~500 calls)",
                            "url": f"{BASE_URL}/buy-credits",
                            "price": "$5"
                        },
                        "option_2": {
                            "label": "Pay per call with USDC on Base",
                            "docs": f"{BASE_URL}/discover",
                            "price": "$0.01–$0.25 per call"
                        }
                    },
                    "tip": f"Use 'Authorization: Bearer apk_xxx' header to skip daily limits.",
                    "you_called": path,
                    "calls_used_today": status["calls_used_today"],
                    "buy_credits": f"{BASE_URL}/buy-credits",
                }).encode()
                start_response("402 Payment Required", [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(nudge))),
                    ("Access-Control-Allow-Origin", "*"),
                    ("X-Powered-By", "claude-haiku-4-5 + x402"),
                ])
                return [nudge]
        except Exception:
            pass

    return _x402_wsgi(environ, start_response)


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
        deduction = deduct_metered(
            api_key, result["input_tokens"], result["output_tokens"],
            cfg["input_cost_per_m"], cfg["output_cost_per_m"],
        )
        if deduction:
            result["metered_cost"] = deduction["cost"]
            result["balance_remaining"] = deduction["balance_remaining"]
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

_discovery_jobs: dict = {}
_scheduler = BackgroundScheduler(daemon=True)
_scheduler.add_job(lambda: run_all_agents(claude), "cron", hour=3, minute=0)
_scheduler.add_job(lambda: run_hourly(claude), "interval", hours=1)
_scheduler.add_job(lambda: run_daily(claude), "cron", hour=6, minute=0)
_scheduler.add_job(lambda: run_weekly(claude), "cron", day_of_week="mon", hour=7, minute=0)
_scheduler.add_job(lambda: _run_agent_economy(), "interval", minutes=30)
_scheduler.start()

# Generate blog posts on first startup if none exist
import threading as _threading
_threading.Thread(target=lambda: generate_all_blog_posts(claude), daemon=True).start()
# Run initial canary after 60s to let service stabilize
_threading.Timer(60.0, lambda: run_canary()).start()


def parse_json_from_claude(text):
    """Extract a JSON object from Claude's response even if wrapped in markdown."""
    import re
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None


def agent_response(data: dict, endpoint: str) -> dict:
    """Wrap result with standard agent-friendly metadata."""
    data["_meta"] = {
        "endpoint": endpoint,
        "model": "claude-haiku-4-5-20251001",
        "network": EVM_NETWORK,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    return data


@app.before_request
def track_referral():
    ref = request.args.get("ref", "").strip()
    if ref and len(ref) <= 64:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
        try:
            record_click(ref, ip, request.path, request.headers.get("User-Agent", ""))
        except Exception:
            pass


@app.after_request
def add_cors(response):
    import uuid
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Payment, Authorization, Accept, X-Idempotency-Key"
    response.headers["Access-Control-Expose-Headers"] = "X-Request-ID, X-Payment-Info"
    response.headers["X-Request-ID"] = request.headers.get("X-Idempotency-Key", str(uuid.uuid4())[:8])
    response.headers["X-Powered-By"] = "claude-haiku-4-5 + x402"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "bad_request", "message": str(e)}), 400


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not_found", "message": "Endpoint not found. GET /discover for available endpoints.", "discover": "https://api.aipaygent.xyz/discover"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "method_not_allowed", "message": str(e)}), 405


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "internal_server_error", "message": "An error occurred processing your request. Please retry.", "retry": True}), 500


@app.route("/<path:path>", methods=["OPTIONS"])
def options(path):
    return "", 204


@app.route("/models", methods=["GET"])
def models_list():
    """List all available AI models with pricing."""
    return jsonify({"models": list_models(), "default": "claude-haiku"})


@app.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json() or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "url required", "hint": "POST {\"url\": \"https://example.com\"}"}), 400
    result = scrape_url(url)
    log_payment("/scrape", 0.01, request.remote_addr)
    return jsonify(result)


@app.route("/search", methods=["POST"])
def search_endpoint():
    data = request.get_json() or {}
    query = data.get("query", "")
    n = min(int(data.get("n", 5)), 10)
    if not query:
        return jsonify({"error": "query required", "hint": "POST {\"query\": \"your search\", \"n\": 5}"}), 400
    result = search_web(query, n=n)
    log_payment("/search", 0.01, request.remote_addr)
    return jsonify(result)


@app.route("/research", methods=["POST"])
def research():
    data = request.get_json() or {}
    question = data.get("question", "")
    if not question:
        return jsonify({"error": "question required", "hint": "POST {\"question\": \"your research question\"}"}), 400

    search_result = search_web(question, n=5)
    if "error" in search_result:
        return jsonify(search_result), 422
    top_urls = [r["url"] for r in search_result["results"][:3]]

    pages = []
    for url in top_urls:
        scraped = scrape_url(url, timeout=8)
        if "error" not in scraped and scraped.get("word_count", 0) > 50:
            pages.append(scraped)

    if not pages:
        return jsonify({"error": "could not retrieve source pages"}), 422

    context = "\n\n---\n\n".join(
        f"Source: {p['url']}\n\n{p['text'][:2000]}" for p in pages
    )
    result, err = _call_llm(
        [{"role": "user", "content": f"Answer the following question based on the sources below. Include inline citations like [1], [2] etc. Be thorough but concise.\n\nQuestion: {question}\n\nSources:\n{context}"}],
        max_tokens=1500, endpoint="/research",
    )
    if err:
        return jsonify({"error": err}), 400
    sources = [{"title": r["title"], "url": r["url"]} for r in search_result["results"][:3]]
    log_payment("/research", 0.15, request.remote_addr)
    return jsonify({
        "question": question,
        "answer": result["text"],
        "sources": sources,
        "model": result["model"],
    })


@app.route("/write", methods=["POST"])
def write():
    data = request.get_json() or {}
    spec = data.get("spec", "")
    content_type = data.get("type", "article")
    if not spec:
        return jsonify({"error": "spec required"}), 400

    result, err = _call_llm(
        [{"role": "user", "content": f"Write a {content_type} based on this spec. Return only the written content, no preamble.\n\nSpec: {spec}"}],
        max_tokens=2048, endpoint="/write",
    )
    if err:
        return jsonify({"error": err}), 400
    log_payment("/write", 0.05, request.remote_addr)
    return jsonify(agent_response({"result": result["text"], "type": content_type, "model": result["model"]}, "/write"))


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json() or {}
    content = data.get("content", "")
    question = data.get("question", "Provide a structured analysis")
    if not content:
        return jsonify({"error": "content required", "hint": "POST {\"content\": \"text to analyze\", \"question\": \"optional focus\"}"}), 400

    result, err = _call_llm(
        [{"role": "user", "content": (
            f'Analyze the following content. Focus: {question}\n\n'
            f'Return a JSON object with keys: '
            f'"conclusion" (string, 1-2 sentences), '
            f'"findings" (array of 4-6 key finding strings), '
            f'"sentiment" (string: positive/negative/neutral/mixed), '
            f'"confidence" (number 0-1).\n\n'
            f'Content:\n{content}'
        )}],
        system="You are an analytical assistant. Always respond with valid JSON only — no markdown, no preamble.",
        max_tokens=1024, endpoint="/analyze",
    )
    if err:
        return jsonify({"error": err}), 400
    raw = result["text"]
    structured = parse_json_from_claude(raw)
    log_payment("/analyze", 0.02, request.remote_addr)
    if structured:
        return jsonify(agent_response({"question": question, "model": result["model"], **structured}, "/analyze"))
    return jsonify(agent_response({"question": question, "result": raw, "model": result["model"]}, "/analyze"))


@app.route("/code", methods=["POST"])
def code():
    data = request.get_json() or {}
    description = data.get("description", "")
    language = data.get("language", "Python")
    if not description:
        return jsonify({"error": "description required"}), 400

    result, err = _call_llm(
        [{"role": "user", "content": f"Write {language} code for the following. Return only the code, no explanation.\n\n{description}"}],
        max_tokens=2048, endpoint="/code",
    )
    if err:
        return jsonify({"error": err}), 400
    log_payment("/code", 0.05, request.remote_addr)
    return jsonify(agent_response({"result": result["text"], "language": language, "model": result["model"]}, "/code"))


@app.route("/summarize", methods=["POST"])
def summarize():
    data = request.get_json() or {}
    text = data.get("text", "")
    length = data.get("length", "bullets")
    if not text:
        return jsonify({"error": "text required"}), 400
    result, err = _call_llm(
        [{"role": "user", "content": f"Summarize in {length} form:\n\n{text}"}],
        max_tokens=1024, endpoint="/summarize",
    )
    if err:
        return jsonify({"error": err}), 400
    log_payment("/summarize", 0.01, request.remote_addr)
    return jsonify(agent_response({
        "summary": result["text"], "original_length": len(text),
        "model": result["model"], "tokens": result["input_tokens"] + result["output_tokens"],
    }, "/summarize"))


@app.route("/translate", methods=["POST"])
def translate():
    data = request.get_json() or {}
    text = data.get("text", "")
    target_language = data.get("language", "Spanish")
    if not text:
        return jsonify({"error": "text required"}), 400

    result, err = _call_llm(
        [{"role": "user", "content": f"Translate the following text to {target_language}. Return only the translation.\n\n{text}"}],
        max_tokens=2048, endpoint="/translate",
    )
    if err:
        return jsonify({"error": err}), 400
    log_payment("/translate", 0.02, request.remote_addr)
    return jsonify(agent_response({"result": result["text"], "language": target_language, "model": result["model"]}, "/translate"))


@app.route("/social", methods=["POST"])
def social():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    platforms = data.get("platforms", ["twitter", "linkedin", "instagram"])
    tone = data.get("tone", "engaging")
    if not topic:
        return jsonify({"error": "topic required"}), 400

    platform_list = ", ".join(platforms) if isinstance(platforms, list) else str(platforms)
    result, err = _call_llm(
        [{"role": "user", "content": (
            f'Write {tone} social media posts for these platforms: {platform_list}. '
            f'Topic: {topic}\n\n'
            f'Return a JSON object with each platform name as a key and the post text as the value. '
            f'Respect character limits: twitter=280 chars, linkedin=3000 chars, instagram=2200 chars.'
        )}],
        system="You are a social media expert. Always respond with valid JSON only — no markdown, no preamble.",
        max_tokens=1024, endpoint="/social",
    )
    if err:
        return jsonify({"error": err}), 400
    raw = result["text"]
    structured = parse_json_from_claude(raw)
    log_payment("/social", 0.03, request.remote_addr)
    if structured:
        return jsonify(agent_response({"topic": topic, "platforms": platforms, "posts": structured, "model": result["model"]}, "/social"))
    return jsonify(agent_response({"topic": topic, "platforms": platforms, "result": raw, "model": result["model"]}, "/social"))


def sentiment_inner(text, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Analyze the sentiment of this text. Return JSON with: '
        f'"polarity" (positive/negative/neutral/mixed), "score" (-1.0 to 1.0), '
        f'"confidence" (0-1), "emotions" (array of detected emotions like joy/anger/fear/sadness/surprise), '
        f'"key_phrases" (array of up to 5 sentiment-driving phrases).\n\nText: {text[:2000]}'
    )}], system="You are a sentiment analysis assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=256)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"text_preview": text[:100], "model": r["model"], **(s if s else {"polarity": raw, "score": 0, "confidence": 0.5})}


def keywords_inner(text, max_keywords=10, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Extract keywords from this text. Return JSON with: '
        f'"keywords" (array of up to {max_keywords} single-word keywords, most important first), '
        f'"topics" (array of up to 5 broader topic phrases), '
        f'"tags" (array of up to 8 hashtag-style tags without #), '
        f'"language" (detected language).\n\nText: {text[:3000]}'
    )}], system="You are a keyword extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"keywords": [], "topics": [], "tags": [], "result": raw}), "model": r["model"]}


def compare_inner(text_a, text_b, focus="", model="claude-haiku"):
    if not text_a or not text_b:
        return {"error": "both text_a and text_b required"}
    focus_str = f" Focus on: {focus}." if focus else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Compare these two texts.{focus_str} Return JSON with: '
        f'"similarities" (array of shared points), "differences" (array of key differences), '
        f'"recommendation" (string — which is better and why, or null if not applicable), '
        f'"similarity_score" (0-1, how similar they are).\n\n'
        f'Text A:\n{text_a[:2000]}\n\nText B:\n{text_b[:2000]}'
    )}], system="You are a comparison assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=768)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"result": raw}), "model": r["model"]}


def transform_inner(text, instruction, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    if not instruction:
        return {"error": "instruction required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Transform the following text according to this instruction. Return ONLY the transformed text, nothing else.\n\n'
        f'Instruction: {instruction}\n\nText:\n{text[:3000]}'
    )}], max_tokens=2048)
    return {"result": r["text"], "instruction": instruction, "model": r["model"]}


def chat_inner(messages, system_prompt="", model="claude-haiku"):
    if not messages or not isinstance(messages, list):
        return {"error": "messages array required"}
    valid = [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
    if not valid:
        return {"error": "messages must be array of {role, content} objects with role=user|assistant"}
    r = call_model(model, valid[-20:], system=system_prompt or "", max_tokens=1024)
    return {"reply": r["text"], "role": "assistant", "turn": len(valid) + 1, "model": r["model"]}


@app.route("/sentiment", methods=["POST"])
def sentiment():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"your text here\"}"}), 400
    result = sentiment_inner(text, model=data.get("model", "claude-haiku"))
    log_payment("/sentiment", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/sentiment"))


@app.route("/keywords", methods=["POST"])
def keywords():
    data = request.get_json() or {}
    text = data.get("text", "")
    max_kw = min(int(data.get("max_keywords", 10)), 30)
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"your text\", \"max_keywords\": 10}"}), 400
    result = keywords_inner(text, max_kw, model=data.get("model", "claude-haiku"))
    log_payment("/keywords", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/keywords"))


@app.route("/compare", methods=["POST"])
def compare():
    data = request.get_json() or {}
    text_a = data.get("text_a", "")
    text_b = data.get("text_b", "")
    focus = data.get("focus", "")
    if not text_a or not text_b:
        return jsonify({"error": "text_a and text_b required", "hint": "POST {\"text_a\": \"...\", \"text_b\": \"...\", \"focus\": \"optional\"}"}), 400
    result = compare_inner(text_a, text_b, focus, model=data.get("model", "claude-haiku"))
    log_payment("/compare", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/compare"))


@app.route("/transform", methods=["POST"])
def transform():
    data = request.get_json() or {}
    text = data.get("text", "")
    instruction = data.get("instruction", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"instruction\": \"make it formal\"}"}), 400
    if not instruction:
        return jsonify({"error": "instruction required", "hint": "e.g. 'make it formal', 'convert to bullet points', 'rewrite for a 5-year-old'"}), 400
    result = transform_inner(text, instruction, model=data.get("model", "claude-haiku"))
    log_payment("/transform", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/transform"))


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json() or {}
    messages = data.get("messages", [])
    system_prompt = data.get("system", "")
    if not messages:
        return jsonify({"error": "messages required", "hint": "POST {\"messages\": [{\"role\": \"user\", \"content\": \"hello\"}], \"system\": \"optional system prompt\"}"}), 400
    result = chat_inner(messages, system_prompt, model=data.get("model", "claude-haiku"))
    log_payment("/chat", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/chat"))


def plan_inner(goal, context="", steps=7, model="claude-haiku"):
    if not goal:
        return {"error": "goal required"}
    ctx = f"\nContext: {context}" if context else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Create a step-by-step action plan for this goal.{ctx}\n'
        f'Return JSON with: "goal" (string), "steps" (array of up to {steps} objects each with "step" number, "action" string, "why" string), '
        f'"estimated_effort" (low/medium/high), "first_action" (the single most important first step).\n\nGoal: {goal}'
    )}], system="You are a strategic planning assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"goal": goal, "result": raw}), "model": r["model"]}


def decide_inner(decision, options=None, criteria="", model="claude-haiku"):
    if not decision:
        return {"error": "decision required"}
    opts_str = f"\nOptions to evaluate: {', '.join(options)}" if options else ""
    crit_str = f"\nCriteria to weigh: {criteria}" if criteria else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Help make this decision.{opts_str}{crit_str}\n'
        f'Return JSON with: "decision" (string), "recommendation" (string — the best choice), '
        f'"reasoning" (string — why), "pros" (array), "cons" (array), "risks" (array), "confidence" (0-1).\n\nDecision: {decision}'
    )}], system="You are a decision analysis assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"decision": decision, "result": raw}), "model": r["model"]}


def proofread_inner(text, style="professional", model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Proofread this text for grammar, spelling, punctuation, and clarity. Style: {style}.\n'
        f'Return JSON with: "corrected" (the fixed text), "issues" (array of objects with "type", "original", "suggestion"), '
        f'"score" (1-10 writing quality), "summary" (one sentence describing overall quality).\n\nText:\n{text[:3000]}'
    )}], system="You are a proofreading assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=2048)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"corrected": raw, "issues": [], "score": 7, "summary": "Proofread complete"}), "model": r["model"]}


def explain_inner(concept, level="beginner", analogy=True, model="claude-haiku"):
    if not concept:
        return {"error": "concept required"}
    analogy_str = "Include a simple real-world analogy." if analogy else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Explain this concept at a {level} level. {analogy_str}\n'
        f'Return JSON with: "explanation" (clear explanation for {level} level), '
        f'"analogy" (simple real-world comparison or null), "key_points" (array of 3-5 key takeaways), '
        f'"common_misconceptions" (array of 1-2 things people get wrong, or empty array).\n\nConcept: {concept}'
    )}], system="You are an expert educator. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=768)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"explanation": raw, "analogy": None, "key_points": [], "common_misconceptions": []}), "model": r["model"]}


def questions_inner(content, qtype="faq", count=5, model="claude-haiku"):
    if not content:
        return {"error": "content required"}
    type_map = {"faq": "frequently asked questions", "interview": "interview questions", "quiz": "quiz questions with answers", "comprehension": "reading comprehension questions"}
    type_desc = type_map.get(qtype, qtype)
    r = call_model(model, [{"role": "user", "content": (
        f'Generate {count} {type_desc} based on this content.\n'
        f'Return JSON with: "questions" (array of objects with "question" string and "answer" string).\n\nContent:\n{content[:3000]}'
    )}], system="You are a question generation assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"questions": [], "result": raw}), "model": r["model"]}


def outline_inner(topic, depth=2, sections=6, model="claude-haiku"):
    if not topic:
        return {"error": "topic required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Generate a structured outline for this topic with {depth} levels of depth and up to {sections} main sections.\n'
        f'Return JSON with: "title" (string), "sections" (array of objects with "heading", "summary", "subsections" array of strings).\n\nTopic: {topic}'
    )}], system="You are an outline and structure expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"title": topic, "result": raw}), "model": r["model"]}


def email_inner(purpose, tone="professional", context="", recipient="", length="medium", model="claude-haiku"):
    if not purpose:
        return {"error": "purpose required"}
    parts = []
    if recipient: parts.append(f"Recipient: {recipient}")
    if context: parts.append(f"Context: {context}")
    extra = "\n".join(parts)
    r = call_model(model, [{"role": "user", "content": (
        f'Write a {tone} email. Length: {length} (short=3-4 sentences, medium=2-3 paragraphs, long=4+ paragraphs).\n{extra}\n'
        f'Return JSON with: "subject" (string), "body" (full email body text), "tone" (string), "word_count" (number).\n\nPurpose: {purpose}'
    )}], system="You are an email writing assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"subject": purpose, "body": raw, "tone": tone}), "model": r["model"]}


def sql_inner(description, dialect="postgresql", schema="", model="claude-haiku"):
    if not description:
        return {"error": "description required"}
    schema_str = f"\nDatabase schema:\n{schema}" if schema else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Write a {dialect} SQL query for this description.{schema_str}\n'
        f'Return JSON with: "query" (the SQL query), "explanation" (what it does), '
        f'"dialect" (string), "notes" (any assumptions or caveats, or null).\n\nDescription: {description}'
    )}], system="You are a SQL expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"query": raw, "explanation": description, "dialect": dialect, "notes": None}), "model": r["model"]}


def regex_inner(description, language="python", flags="", model="claude-haiku"):
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Generate a regex pattern for {language} that matches: {description}. Flags hint: {flags or "none"}.\n'
        f'Return JSON with: "pattern" (the regex string), "flags" (flags to use, or empty string), '
        f'"explanation" (what it matches and why), "examples" (array of 3 strings that would match), '
        f'"non_examples" (array of 2 strings that would NOT match).'
    )}], system="You are a regex expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"pattern": raw, "flags": "", "explanation": description}), "model": r["model"]}


def mock_inner(description, count=5, fmt="json", model="claude-haiku"):
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Generate {count} realistic mock data records for: {description}. Output format: {fmt}.\n'
        f'Return JSON with: "data" (array of {count} records as objects), "schema" (object describing each field and its type), '
        f'"format" (string: json/csv/list).'
    )}], system="You are a mock data generation expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1536)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"data": [], "result": raw, "format": fmt}), "model": r["model"]}


@app.route("/plan", methods=["POST"])
def plan():
    data = request.get_json() or {}
    goal = data.get("goal", "")
    if not goal:
        return jsonify({"error": "goal required", "hint": "POST {\"goal\": \"launch a product\", \"context\": \"optional\", \"steps\": 7}"}), 400
    result = plan_inner(goal, data.get("context", ""), int(data.get("steps", 7)), model=data.get("model", "claude-haiku"))
    log_payment("/plan", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/plan"))


@app.route("/decide", methods=["POST"])
def decide():
    data = request.get_json() or {}
    decision = data.get("decision", "")
    if not decision:
        return jsonify({"error": "decision required", "hint": "POST {\"decision\": \"...\", \"options\": [\"A\",\"B\"], \"criteria\": \"cost and speed\"}"}), 400
    result = decide_inner(decision, data.get("options"), data.get("criteria", ""), model=data.get("model", "claude-haiku"))
    log_payment("/decide", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/decide"))


@app.route("/proofread", methods=["POST"])
def proofread():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"style\": \"professional\"}"}), 400
    result = proofread_inner(text, data.get("style", "professional"), model=data.get("model", "claude-haiku"))
    log_payment("/proofread", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/proofread"))


@app.route("/explain", methods=["POST"])
def explain():
    data = request.get_json() or {}
    concept = data.get("concept", "")
    if not concept:
        return jsonify({"error": "concept required", "hint": "POST {\"concept\": \"quantum entanglement\", \"level\": \"beginner\"}"}), 400
    result = explain_inner(concept, data.get("level", "beginner"), data.get("analogy", True), model=data.get("model", "claude-haiku"))
    log_payment("/explain", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/explain"))


@app.route("/questions", methods=["POST"])
def questions():
    data = request.get_json() or {}
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "content required", "hint": "POST {\"content\": \"...\", \"type\": \"faq|interview|quiz|comprehension\", \"count\": 5}"}), 400
    result = questions_inner(content, data.get("type", "faq"), int(data.get("count", 5)), model=data.get("model", "claude-haiku"))
    log_payment("/questions", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/questions"))


@app.route("/outline", methods=["POST"])
def outline():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required", "hint": "POST {\"topic\": \"machine learning\", \"depth\": 2, \"sections\": 6}"}), 400
    result = outline_inner(topic, int(data.get("depth", 2)), int(data.get("sections", 6)), model=data.get("model", "claude-haiku"))
    log_payment("/outline", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/outline"))


@app.route("/email", methods=["POST"])
def email():
    data = request.get_json() or {}
    purpose = data.get("purpose", "")
    if not purpose:
        return jsonify({"error": "purpose required", "hint": "POST {\"purpose\": \"follow up on interview\", \"tone\": \"professional\", \"recipient\": \"hiring manager\"}"}), 400
    result = email_inner(purpose, data.get("tone", "professional"), data.get("context", ""), data.get("recipient", ""), data.get("length", "medium"), model=data.get("model", "claude-haiku"))
    log_payment("/email", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/email"))


@app.route("/sql", methods=["POST"])
def sql():
    data = request.get_json() or {}
    description = data.get("description", "")
    if not description:
        return jsonify({"error": "description required", "hint": "POST {\"description\": \"get all users who signed up last month\", \"dialect\": \"postgresql\", \"schema\": \"optional\"}"}), 400
    result = sql_inner(description, data.get("dialect", "postgresql"), data.get("schema", ""), model=data.get("model", "claude-haiku"))
    log_payment("/sql", 0.05, request.remote_addr)
    return jsonify(agent_response(result, "/sql"))


@app.route("/regex", methods=["POST"])
def regex():
    data = request.get_json() or {}
    description = data.get("description", "")
    if not description:
        return jsonify({"error": "description required", "hint": "POST {\"description\": \"match email addresses\", \"language\": \"python\"}"}), 400
    result = regex_inner(description, data.get("language", "python"), data.get("flags", ""), model=data.get("model", "claude-haiku"))
    log_payment("/regex", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/regex"))


@app.route("/mock", methods=["POST"])
def mock():
    data = request.get_json() or {}
    description = data.get("description", "")
    if not description:
        return jsonify({"error": "description required", "hint": "POST {\"description\": \"user profiles with name, email, age\", \"count\": 5, \"format\": \"json\"}"}), 400
    result = mock_inner(description, min(int(data.get("count", 5)), 50), data.get("format", "json"), model=data.get("model", "claude-haiku"))
    log_payment("/mock", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/mock"))


@app.route("/score", methods=["POST"])
def score():
    data = request.get_json() or {}
    content = data.get("content", "")
    criteria = data.get("criteria", ["clarity", "accuracy", "engagement"])
    if not content:
        return jsonify({"error": "content required", "hint": "POST {\"content\": \"...\", \"criteria\": [\"clarity\", \"accuracy\"], \"scale\": 10}"}), 400
    result = score_inner(content, criteria, int(data.get("scale", 10)), model=data.get("model", "claude-haiku"))
    log_payment("/score", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/score"))


@app.route("/timeline", methods=["POST"])
def timeline():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"direction\": \"chronological\"}"}), 400
    result = timeline_inner(text, data.get("direction", "chronological"), model=data.get("model", "claude-haiku"))
    log_payment("/timeline", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/timeline"))


@app.route("/action", methods=["POST"])
def action():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"meeting notes or any text with tasks\"}"}), 400
    result = action_inner(text, model=data.get("model", "claude-haiku"))
    log_payment("/action", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/action"))


@app.route("/pitch", methods=["POST"])
def pitch():
    data = request.get_json() or {}
    product = data.get("product", "")
    if not product:
        return jsonify({"error": "product required", "hint": "POST {\"product\": \"...\", \"audience\": \"investors\", \"length\": \"30s\"}"}), 400
    result = pitch_inner(product, data.get("audience", ""), data.get("length", "30s"), model=data.get("model", "claude-haiku"))
    log_payment("/pitch", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/pitch"))


@app.route("/debate", methods=["POST"])
def debate():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required", "hint": "POST {\"topic\": \"AI will replace programmers\", \"perspective\": \"balanced\"}"}), 400
    result = debate_inner(topic, data.get("perspective", "balanced"), model=data.get("model", "claude-haiku"))
    log_payment("/debate", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/debate"))


@app.route("/headline", methods=["POST"])
def headline():
    data = request.get_json() or {}
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "content required", "hint": "POST {\"content\": \"...\", \"count\": 5, \"style\": \"engaging\"}"}), 400
    result = headline_inner(content, int(data.get("count", 5)), data.get("style", "engaging"), model=data.get("model", "claude-haiku"))
    log_payment("/headline", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/headline"))


@app.route("/fact", methods=["POST"])
def fact():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"count\": 10}"}), 400
    result = fact_inner(text, int(data.get("count", 10)), model=data.get("model", "claude-haiku"))
    log_payment("/fact", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/fact"))


@app.route("/rewrite", methods=["POST"])
def rewrite():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"audience\": \"5th grader\", \"tone\": \"friendly\"}"}), 400
    result = rewrite_inner(text, data.get("audience", "general audience"), data.get("tone", "neutral"), model=data.get("model", "claude-haiku"))
    log_payment("/rewrite", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/rewrite"))


@app.route("/tag", methods=["POST"])
def tag():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"taxonomy\": [\"tech\", \"ai\", \"business\"], \"max_tags\": 10}"}), 400
    result = tag_inner(text, data.get("taxonomy"), int(data.get("max_tags", 10)), model=data.get("model", "claude-haiku"))
    log_payment("/tag", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/tag"))


@app.route("/pipeline", methods=["POST"])
def pipeline():
    data = request.get_json() or {}
    steps = data.get("steps", [])
    if not steps:
        return jsonify({"error": "steps array required", "hint": "POST {\"steps\": [{\"endpoint\": \"research\", \"input\": {\"topic\": \"AI\"}}, {\"endpoint\": \"summarize\", \"input\": {\"text\": \"{{prev}}\"}}]}"}), 400
    result = pipeline_inner(steps)
    log_payment("/pipeline", 0.15, request.remote_addr)
    return jsonify(agent_response(result, "/pipeline"))


BATCH_HANDLERS = {
    "research": lambda d: research_inner(d.get("topic", ""), model=d.get("model", "claude-haiku")),
    "summarize": lambda d: summarize_inner(d.get("text", ""), d.get("length", "short"), model=d.get("model", "claude-haiku")),
    "analyze": lambda d: analyze_inner(d.get("content", ""), d.get("question", "Provide a structured analysis"), model=d.get("model", "claude-haiku")),
    "translate": lambda d: translate_inner(d.get("text", ""), d.get("language", "Spanish"), model=d.get("model", "claude-haiku")),
    "social": lambda d: social_inner(d.get("topic", ""), d.get("platforms", ["twitter", "linkedin", "instagram"]), d.get("tone", "engaging"), model=d.get("model", "claude-haiku")),
    "write": lambda d: write_inner(d.get("spec", ""), d.get("type", "article"), model=d.get("model", "claude-haiku")),
    "code": lambda d: code_inner(d.get("description", ""), d.get("language", "Python"), model=d.get("model", "claude-haiku")),
    "extract": lambda d: extract_inner(d.get("text", ""), d.get("schema", ""), d.get("fields", []), model=d.get("model", "claude-haiku")),
    "qa": lambda d: qa_inner(d.get("context", ""), d.get("question", ""), model=d.get("model", "claude-haiku")),
    "classify": lambda d: classify_inner(d.get("text", ""), d.get("categories", []), model=d.get("model", "claude-haiku")),
    "sentiment": lambda d: sentiment_inner(d.get("text", ""), model=d.get("model", "claude-haiku")),
    "keywords": lambda d: keywords_inner(d.get("text", ""), d.get("max_keywords", 10), model=d.get("model", "claude-haiku")),
    "compare": lambda d: compare_inner(d.get("text_a", ""), d.get("text_b", ""), d.get("focus", ""), model=d.get("model", "claude-haiku")),
    "transform": lambda d: transform_inner(d.get("text", ""), d.get("instruction", ""), model=d.get("model", "claude-haiku")),
    "chat": lambda d: chat_inner(d.get("messages", []), d.get("system", ""), model=d.get("model", "claude-haiku")),
    "plan": lambda d: plan_inner(d.get("goal", ""), d.get("context", ""), int(d.get("steps", 7)), model=d.get("model", "claude-haiku")),
    "decide": lambda d: decide_inner(d.get("decision", ""), d.get("options"), d.get("criteria", ""), model=d.get("model", "claude-haiku")),
    "proofread": lambda d: proofread_inner(d.get("text", ""), d.get("style", "professional"), model=d.get("model", "claude-haiku")),
    "explain": lambda d: explain_inner(d.get("concept", ""), d.get("level", "beginner"), d.get("analogy", True), model=d.get("model", "claude-haiku")),
    "questions": lambda d: questions_inner(d.get("content", ""), d.get("type", "faq"), int(d.get("count", 5)), model=d.get("model", "claude-haiku")),
    "outline": lambda d: outline_inner(d.get("topic", ""), int(d.get("depth", 2)), int(d.get("sections", 6)), model=d.get("model", "claude-haiku")),
    "email": lambda d: email_inner(d.get("purpose", ""), d.get("tone", "professional"), d.get("context", ""), d.get("recipient", ""), d.get("length", "medium"), model=d.get("model", "claude-haiku")),
    "sql": lambda d: sql_inner(d.get("description", ""), d.get("dialect", "postgresql"), d.get("schema", ""), model=d.get("model", "claude-haiku")),
    "regex": lambda d: regex_inner(d.get("description", ""), d.get("language", "python"), d.get("flags", ""), model=d.get("model", "claude-haiku")),
    "mock": lambda d: mock_inner(d.get("description", ""), int(d.get("count", 5)), d.get("format", "json"), model=d.get("model", "claude-haiku")),
    "score": lambda d: score_inner(d.get("content", ""), d.get("criteria", ["clarity", "accuracy", "engagement"]), int(d.get("scale", 10)), model=d.get("model", "claude-haiku")),
    "timeline": lambda d: timeline_inner(d.get("text", ""), d.get("direction", "chronological"), model=d.get("model", "claude-haiku")),
    "action": lambda d: action_inner(d.get("text", ""), model=d.get("model", "claude-haiku")),
    "pitch": lambda d: pitch_inner(d.get("product", ""), d.get("audience", ""), d.get("length", "30s"), model=d.get("model", "claude-haiku")),
    "debate": lambda d: debate_inner(d.get("topic", ""), d.get("perspective", "balanced"), model=d.get("model", "claude-haiku")),
    "headline": lambda d: headline_inner(d.get("content", ""), int(d.get("count", 5)), d.get("style", "engaging"), model=d.get("model", "claude-haiku")),
    "fact": lambda d: fact_inner(d.get("text", ""), int(d.get("count", 10)), model=d.get("model", "claude-haiku")),
    "rewrite": lambda d: rewrite_inner(d.get("text", ""), d.get("audience", "general audience"), d.get("tone", "neutral"), model=d.get("model", "claude-haiku")),
    "tag": lambda d: tag_inner(d.get("text", ""), d.get("taxonomy"), int(d.get("max_tags", 10)), model=d.get("model", "claude-haiku")),
}


def research_inner(topic, model="claude-haiku"):
    if not topic:
        return {"error": "topic required"}
    r = call_model(model, [{"role": "user", "content": f'Research this topic. Return JSON with keys: "summary" (string), "key_points" (array of 5), "sources_to_check" (array of 3 URLs). Topic: {topic}'}],
        system="You are a research assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"topic": topic, "model": r["model"], **(s if s else {"result": raw})}


def summarize_inner(text, length, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": f"Summarize. Length: {length} (short=2-3 sentences, medium=1 paragraph, detailed=3-4 paragraphs). Return only the summary.\n\n{text}"}],
        max_tokens=512)
    return {"result": r["text"], "length": length, "model": r["model"]}


def analyze_inner(content, question, model="claude-haiku"):
    if not content:
        return {"error": "content required"}
    r = call_model(model, [{"role": "user", "content": f'Analyze this. Focus: {question}\nReturn JSON with: "conclusion" (string), "findings" (array), "sentiment" (string), "confidence" (0-1).\n\nContent:\n{content}'}],
        system="You are an analytical assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"question": question, "model": r["model"], **(s if s else {"result": raw})}


def translate_inner(text, language, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": f"Translate to {language}. Return only the translation.\n\n{text}"}],
        max_tokens=2048)
    return {"result": r["text"], "language": language, "model": r["model"]}


def social_inner(topic, platforms, tone, model="claude-haiku"):
    if not topic:
        return {"error": "topic required"}
    platform_list = ", ".join(platforms) if isinstance(platforms, list) else str(platforms)
    r = call_model(model, [{"role": "user", "content": f'Write {tone} posts for: {platform_list}. Topic: {topic}\nReturn JSON with each platform as key, post text as value.'}],
        system="You are a social media expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"topic": topic, "platforms": platforms, "model": r["model"], **({"posts": s} if s else {"result": raw})}


def write_inner(spec, content_type, model="claude-haiku"):
    if not spec:
        return {"error": "spec required"}
    r = call_model(model, [{"role": "user", "content": f"Write a {content_type}. Return only the content.\n\nSpec: {spec}"}],
        max_tokens=2048)
    return {"result": r["text"], "type": content_type, "model": r["model"]}


def code_inner(description, language, model="claude-haiku"):
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": f"Write {language} code. Return only the code.\n\n{description}"}],
        max_tokens=2048)
    return {"result": r["text"], "language": language, "model": r["model"]}


def extract_inner(text, schema_desc, fields, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    if fields:
        fields_str = ", ".join(f'"{f}"' for f in fields[:20])
        prompt = f'Extract these fields from the text and return as JSON: {fields_str}.\nIf a field is not found, use null.\n\nText:\n{text[:4000]}'
    elif schema_desc:
        prompt = f'Extract data matching this schema and return as JSON: {schema_desc}\n\nText:\n{text[:4000]}'
    else:
        prompt = f'Extract all key entities, facts, dates, names, and values from this text. Return as JSON with descriptive keys.\n\nText:\n{text[:4000]}'
    r = call_model(model, [{"role": "user", "content": prompt}],
        system="You are a data extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"extracted": s if s else raw, "fields_requested": fields or schema_desc or "auto", "model": r["model"]}


def qa_inner(context, question, model="claude-haiku"):
    if not context:
        return {"error": "context required"}
    if not question:
        return {"error": "question required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Answer the question using only the provided context. '
        f'Return JSON with: "answer" (string), "confidence" (0-1), "found_in_context" (boolean), "quote" (relevant excerpt or null).\n\n'
        f'Context:\n{context[:4000]}\n\nQuestion: {question}'
    )}], system="You are a precise question-answering assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"question": question, "model": r["model"], **(s if s else {"answer": raw, "confidence": 0.5, "found_in_context": True, "quote": None})}


def classify_inner(text, categories, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    if not categories or not isinstance(categories, list):
        return {"error": "categories array required", "hint": "e.g. [\"positive\", \"negative\", \"neutral\"]"}
    cats_str = ", ".join(f'"{c}"' for c in categories[:20])
    r = call_model(model, [{"role": "user", "content": (
        f'Classify this text into one of these categories: {cats_str}. '
        f'Return JSON with: "category" (the best match), "confidence" (0-1), "scores" (object with each category and its score 0-1).\n\n'
        f'Text: {text[:2000]}'
    )}], system="You are a text classification assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=256)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"text_preview": text[:100], "categories": categories, "model": r["model"], **(s if s else {"category": raw, "confidence": 0.5, "scores": {}})}


def score_inner(content, criteria, scale=10, model="claude-haiku"):
    criteria_str = json.dumps(criteria) if isinstance(criteria, list) else str(criteria)
    r = call_model(model, [{"role": "user", "content": (
        f'Score this content on a scale of 1-{scale}. Criteria: {criteria_str}. '
        f'Return JSON with: "overall_score" (number), "scores" (object with each criterion and its score), '
        f'"strengths" (array), "weaknesses" (array), "recommendation" (string).\n\nContent:\n{content[:3000]}'
    )}], system="You are a content scoring assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"criteria": criteria, "scale": scale, "model": r["model"], **(s if s else {"result": raw})}


def timeline_inner(text, direction="chronological", model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Extract or reconstruct a {direction} timeline from this text. '
        f'Return JSON with: "events" (array of objects with "date", "event", "significance"), '
        f'"span" (string describing total time range), "summary" (string).\n\nText:\n{text[:3000]}'
    )}], system="You are a timeline extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"direction": direction, "model": r["model"], **(s if s else {"result": raw})}


def action_inner(text, model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Extract all action items and tasks from this text. '
        f'Return JSON with: "actions" (array of objects with "task", "owner" (string or null), "due_date" (string or null), "priority" (high/medium/low)), '
        f'"count" (integer), "summary" (string).\n\nText:\n{text[:3000]}'
    )}], system="You are an action item extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"model": r["model"], **(s if s else {"result": raw})}


def pitch_inner(product, audience, length="30s", model="claude-haiku"):
    words = {"15s": 40, "30s": 75, "60s": 150}.get(length, 75)
    r = call_model(model, [{"role": "user", "content": (
        f'Write an elevator pitch (~{words} words) for: {product}. Target audience: {audience or "general"}. '
        f'Return JSON with: "hook" (opening line), "value_prop" (core benefit), "call_to_action" (closing ask), '
        f'"full_pitch" (complete {length} pitch), "word_count" (integer).'
    )}], system="You are a pitch writing assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"product": product, "audience": audience, "length": length, "model": r["model"], **(s if s else {"result": raw})}


def debate_inner(topic, perspective="balanced", model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Generate debate arguments for this topic: {topic}. Perspective: {perspective}. '
        f'Return JSON with: "for" (array of objects with "argument" and "strength": strong/medium/weak), '
        f'"against" (array of objects with "argument" and "strength"), '
        f'"verdict" (string: which side is stronger), "nuance" (string: key considerations).'
    )}], system="You are a debate assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"topic": topic, "perspective": perspective, "model": r["model"], **(s if s else {"result": raw})}


def headline_inner(content, count=5, style="engaging", model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Generate {count} {style} headlines/titles for this content. '
        f'Return JSON with: "headlines" (array of objects with "text" and "type": clickbait/informative/question/how-to/listicle), '
        f'"best" (the single best headline).\n\nContent:\n{content[:2000]}'
    )}], system="You are a headline writing assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"count": count, "style": style, "model": r["model"], **(s if s else {"result": raw})}


def fact_inner(text, count=10, model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Extract up to {count} factual claims from this text. '
        f'Return JSON with: "facts" (array of objects with "claim" (string), "verifiability": easy/moderate/difficult, '
        f'"source_hint" (string or null), "confidence" (0-1)), "total_claims" (integer).\n\nText:\n{text[:3000]}'
    )}], system="You are a fact extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"model": r["model"], **(s if s else {"result": raw})}


def rewrite_inner(text, audience, tone="neutral", model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Rewrite this text for: {audience}. Tone: {tone}. '
        f'Return only the rewritten text with no explanation.\n\nOriginal:\n{text[:3000]}'
    )}], max_tokens=2048)
    return {"result": r["text"], "audience": audience, "tone": tone, "model": r["model"]}


def tag_inner(text, taxonomy, max_tags=10, model="claude-haiku"):
    taxonomy_str = f"Use only tags from this taxonomy: {json.dumps(taxonomy)}." if taxonomy else "Generate free-form tags."
    r = call_model(model, [{"role": "user", "content": (
        f'Tag this content with up to {max_tags} tags. {taxonomy_str} '
        f'Return JSON with: "tags" (array of strings), "primary_tag" (most relevant tag), '
        f'"categories" (array of 1-3 broad categories).\n\nContent:\n{text[:2000]}'
    )}], system="You are a content tagging assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=256)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"max_tags": max_tags, "taxonomy": taxonomy, "model": r["model"], **(s if s else {"result": raw})}


def pipeline_inner(steps):
    if len(steps) > 5:
        return {"error": "max 5 steps"}
    results = []
    prev_output = None
    for i, step in enumerate(steps):
        endpoint = step.get("endpoint", "").lstrip("/")
        inp = dict(step.get("input", {}))
        if prev_output is not None:
            prev_text = (prev_output.get("result") or prev_output.get("summary") or str(prev_output))[:3000]
            for k, v in inp.items():
                if v in ("{{prev}}", "{{output}}"):
                    inp[k] = prev_text
        handler = BATCH_HANDLERS.get(endpoint)
        if not handler:
            result = {"error": f"unknown endpoint '{endpoint}'"}
        else:
            try:
                result = handler(inp)
            except Exception as e:
                result = {"error": str(e)}
        results.append({"step": i + 1, "endpoint": endpoint, **result})
        prev_output = result
    return {"results": results, "steps": len(steps), "final_output": prev_output}


@app.route("/extract", methods=["POST"])
def extract():
    data = request.get_json() or {}
    url = data.get("url", "")
    text = data.get("text", "")
    schema_desc = data.get("schema", "")
    fields = data.get("fields", [])

    # URL mode: scrape URL first, then extract
    if url:
        if not schema_desc and not fields:
            return jsonify({"error": "schema or fields required with url", "hint": "POST {\"url\": \"...\", \"schema\": {\"field\": \"description\"}}"}), 400
        scraped = scrape_url(url)
        if "error" in scraped:
            return jsonify(scraped), 422
        text = scraped["text"][:6000]

    if not text:
        return jsonify({"error": "text or url required", "hint": "POST {\"text\": \"...\", \"fields\": [\"name\", \"date\"]} or {\"url\": \"...\", \"schema\": {}}"}), 400
    result = extract_inner(text, schema_desc, fields, model=data.get("model", "claude-haiku"))
    log_payment("/extract", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/extract"))


@app.route("/qa", methods=["POST"])
def qa():
    data = request.get_json() or {}
    context = data.get("context", "")
    question = data.get("question", "")
    if not context:
        return jsonify({"error": "context required", "hint": "POST {\"context\": \"document text\", \"question\": \"your question\"}"}), 400
    if not question:
        return jsonify({"error": "question required"}), 400
    result = qa_inner(context, question, model=data.get("model", "claude-haiku"))
    log_payment("/qa", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/qa"))


@app.route("/classify", methods=["POST"])
def classify():
    data = request.get_json() or {}
    text = data.get("text", "")
    categories = data.get("categories", [])
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"categories\": [\"positive\", \"negative\"]}"}), 400
    if not categories:
        return jsonify({"error": "categories required", "hint": "Provide an array of category strings"}), 400
    result = classify_inner(text, categories, model=data.get("model", "claude-haiku"))
    log_payment("/classify", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/classify"))


@app.route("/batch", methods=["POST"])
def batch():
    """Run up to 5 AI operations in one payment. $0.10 flat."""
    data = request.get_json() or {}
    ops = data.get("operations", [])
    if not ops or not isinstance(ops, list):
        return jsonify({"error": "operations array required", "hint": "POST {\"operations\": [{\"endpoint\": \"research\", \"input\": {\"topic\": \"AI\"}}]}"}), 400
    if len(ops) > 5:
        return jsonify({"error": "max 5 operations per batch"}), 400

    results = []
    for op in ops:
        endpoint = op.get("endpoint", "").lstrip("/")
        inp = op.get("input", {})
        handler = BATCH_HANDLERS.get(endpoint)
        if not handler:
            results.append({"endpoint": endpoint, "error": f"unknown endpoint '{endpoint}'. Valid: {list(BATCH_HANDLERS.keys())}"})
        else:
            try:
                result = handler(inp)
                results.append({"endpoint": endpoint, **result})
            except Exception as e:
                results.append({"endpoint": endpoint, "error": str(e)})

    log_payment("/batch", 0.10, request.remote_addr)
    return jsonify(agent_response({"results": results, "count": len(results)}, "/batch"))


LANDING_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGent — AI Economy Infrastructure</title>
<link rel="alternate" type="text/plain" href="/llms.txt" title="LLMs.txt">
<meta name="description" content="Pay-per-use Claude AI API for autonomous agents. Research, write, code, translate — pay in USDC on Base via x402 protocol. No API keys required.">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<meta property="og:type" content="website">
<meta property="og:title" content="AiPayGent — AI Economy Infrastructure">
<meta property="og:description" content="Pay-per-use Claude AI API for autonomous agents. Research, write, code, translate — pay in USDC on Base via x402 protocol.">
<meta property="og:url" content="https://api.aipaygent.xyz">
<meta property="og:image" content="https://api.aipaygent.xyz/og-image.png">
<meta property="og:site_name" content="AiPayGent">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="AiPayGent — AI Economy Infrastructure">
<meta name="twitter:description" content="Pay-per-use Claude AI API for autonomous agents. 140+ endpoints, USDC on Base, no API keys.">
<meta name="twitter:image" content="https://api.aipaygent.xyz/og-image.png">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"WebApplication","name":"AiPayGent","url":"https://api.aipaygent.xyz","description":"Pay-per-use Claude AI API for autonomous agents. 140+ endpoints via x402 micropayments on Base.","applicationCategory":"DeveloperApplication","operatingSystem":"Any","offers":{"@type":"Offer","price":"0.01","priceCurrency":"USD","description":"Per API call, paid in USDC on Base"},"provider":{"@type":"Organization","name":"AiPayGent","url":"https://api.aipaygent.xyz"}}
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&family=IBM+Plex+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #020408;
    --bg2: #070d14;
    --bg3: #0d1a24;
    --green: #00ff9d;
    --blue: #0088ff;
    --cyan: #00d4ff;
    --red: #ff4444;
    --text: #c8d8e8;
    --muted: #4a6070;
    --border: #0d2030;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'IBM Plex Mono', monospace;
    overflow-x: hidden;
    cursor: crosshair;
  }

  /* Grid texture */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,136,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,136,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  /* Scanline effect */
  body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.08) 2px,
      rgba(0,0,0,0.08) 4px
    );
    pointer-events: none;
    z-index: 1;
  }

  .noise {
    position: fixed;
    inset: -200%;
    width: 400%;
    height: 400%;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
    opacity: 0.4;
    pointer-events: none;
    z-index: 0;
    animation: noise 0.5s steps(1) infinite;
  }
  @keyframes noise {
    0%,100% { transform: translate(0,0); }
    10% { transform: translate(-2%,-2%); }
    20% { transform: translate(2%,2%); }
    30% { transform: translate(-1%,1%); }
    40% { transform: translate(1%,-1%); }
    50% { transform: translate(-2%,1%); }
    60% { transform: translate(2%,-1%); }
    70% { transform: translate(-1%,2%); }
    80% { transform: translate(1%,1%); }
    90% { transform: translate(-1%,-2%); }
  }

  .content { position: relative; z-index: 2; }

  /* NAV */
  nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 48px;
    border-bottom: 1px solid var(--border);
    background: rgba(2,4,8,0.9);
    backdrop-filter: blur(10px);
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .logo {
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: 0.15em;
    color: var(--green);
    text-transform: uppercase;
  }
  .logo span { color: var(--muted); }
  .nav-links { display: flex; gap: 32px; }
  .nav-links a {
    color: var(--muted);
    text-decoration: none;
    font-size: 0.75rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    transition: color 0.2s;
  }
  .nav-links a:hover { color: var(--cyan); }
  .status-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.7rem;
    color: var(--green);
    letter-spacing: 0.1em;
  }
  .dot {
    width: 6px; height: 6px;
    background: var(--green);
    border-radius: 50%;
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,100% { opacity: 1; box-shadow: 0 0 6px var(--green); }
    50% { opacity: 0.4; box-shadow: none; }
  }

  /* HERO */
  .hero {
    min-height: 88vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 80px 48px;
    max-width: 1200px;
    margin: 0 auto;
  }
  .tag {
    font-size: 0.7rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--blue);
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .tag::before {
    content: '//';
    color: var(--muted);
  }
  h1 {
    font-size: clamp(2.5rem, 6vw, 5.5rem);
    font-weight: 700;
    line-height: 1.05;
    letter-spacing: -0.02em;
    margin-bottom: 32px;
    color: #fff;
  }
  h1 .accent { color: var(--green); }
  h1 .dim { color: var(--muted); }
  .hero-sub {
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 1.1rem;
    color: var(--muted);
    max-width: 560px;
    line-height: 1.7;
    margin-bottom: 48px;
    font-weight: 300;
  }
  .hero-actions { display: flex; gap: 16px; flex-wrap: wrap; }
  .btn {
    padding: 14px 28px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.8rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    text-decoration: none;
    border: none;
    cursor: pointer;
    transition: all 0.2s;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .btn-primary {
    background: var(--green);
    color: #000;
    font-weight: 700;
  }
  .btn-primary:hover {
    background: #fff;
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(0,255,157,0.3);
  }
  .btn-ghost {
    background: transparent;
    color: var(--cyan);
    border: 1px solid var(--border);
  }
  .btn-ghost:hover {
    border-color: var(--cyan);
    box-shadow: 0 0 20px rgba(0,212,255,0.1);
  }

  /* TICKER */
  .ticker {
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    padding: 12px 0;
    overflow: hidden;
    background: var(--bg2);
  }
  .ticker-inner {
    display: flex;
    gap: 60px;
    animation: scroll 25s linear infinite;
    white-space: nowrap;
  }
  @keyframes scroll {
    from { transform: translateX(0); }
    to { transform: translateX(-50%); }
  }
  .ticker-item {
    font-size: 0.7rem;
    letter-spacing: 0.1em;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .ticker-item .price { color: var(--green); }
  .ticker-item .sep { color: var(--border); }

  /* SERVICES */
  .section {
    max-width: 1200px;
    margin: 0 auto;
    padding: 80px 48px;
  }
  .section-header {
    display: flex;
    align-items: baseline;
    gap: 20px;
    margin-bottom: 48px;
  }
  .section-title {
    font-size: 0.7rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .section-line {
    flex: 1;
    height: 1px;
    background: var(--border);
  }
  .services-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
  }
  .service-card {
    background: var(--bg);
    padding: 32px;
    transition: background 0.2s;
    position: relative;
    overflow: hidden;
  }
  .service-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--blue), transparent);
    transform: scaleX(0);
    transition: transform 0.3s;
  }
  .service-card:hover { background: var(--bg2); }
  .service-card:hover::before { transform: scaleX(1); }
  .service-endpoint {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--cyan);
    margin-bottom: 8px;
    letter-spacing: 0.05em;
  }
  .service-desc {
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.85rem;
    color: var(--muted);
    margin-bottom: 20px;
    line-height: 1.6;
    font-weight: 300;
  }
  .service-price {
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--green);
  }
  .service-price span {
    font-size: 0.7rem;
    color: var(--muted);
    font-weight: 400;
    margin-left: 4px;
  }

  /* HOW IT WORKS */
  .how-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 48px;
    align-items: start;
  }
  .steps { display: flex; flex-direction: column; gap: 0; }
  .step {
    display: flex;
    gap: 24px;
    padding: 24px 0;
    border-bottom: 1px solid var(--border);
    position: relative;
  }
  .step:last-child { border-bottom: none; }
  .step-num {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--blue);
    letter-spacing: 0.1em;
    min-width: 32px;
    padding-top: 2px;
  }
  .step-content h3 {
    font-size: 0.85rem;
    font-weight: 600;
    color: #fff;
    margin-bottom: 6px;
    letter-spacing: 0.05em;
  }
  .step-content p {
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.82rem;
    color: var(--muted);
    line-height: 1.6;
    font-weight: 300;
  }
  .code-block {
    background: var(--bg2);
    border: 1px solid var(--border);
    padding: 28px;
    font-size: 0.78rem;
    line-height: 1.8;
    color: var(--text);
    overflow-x: auto;
    position: relative;
  }
  .code-block::before {
    content: 'EXAMPLE REQUEST';
    display: block;
    font-size: 0.65rem;
    letter-spacing: 0.15em;
    color: var(--muted);
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }
  .c-key { color: var(--cyan); }
  .c-val { color: var(--green); }
  .c-str { color: #ffb86c; }
  .c-muted { color: var(--muted); }

  /* STATS */
  .stats-bar {
    background: var(--bg2);
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    padding: 40px 48px;
  }
  .stats-inner {
    max-width: 1200px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1px;
    background: var(--border);
  }
  .stat {
    background: var(--bg2);
    padding: 24px 32px;
    text-align: center;
  }
  .stat-val {
    font-size: 2rem;
    font-weight: 700;
    color: var(--green);
    display: block;
    margin-bottom: 4px;
  }
  .stat-label {
    font-size: 0.65rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--muted);
  }

  /* FOOTER */
  footer {
    border-top: 1px solid var(--border);
    padding: 32px 48px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    max-width: 1200px;
    margin: 0 auto;
    flex-wrap: wrap;
    gap: 16px;
  }
  .footer-left { font-size: 0.7rem; color: var(--muted); letter-spacing: 0.05em; }
  .footer-left a { color: var(--blue); text-decoration: none; }
  .footer-right { font-size: 0.65rem; color: var(--muted); letter-spacing: 0.05em; text-align: right; }
  .network-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    border: 1px solid var(--border);
    font-size: 0.65rem;
    letter-spacing: 0.1em;
    color: var(--muted);
  }
  .network-badge .dot { width: 5px; height: 5px; background: var(--blue); }

  /* Animations */
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .fade-up { animation: fadeUp 0.6s ease both; }
  .delay-1 { animation-delay: 0.1s; }
  .delay-2 { animation-delay: 0.2s; }
  .delay-3 { animation-delay: 0.3s; }
  .delay-4 { animation-delay: 0.4s; }

  @media (max-width: 768px) {
    nav { padding: 16px 24px; }
    .nav-links { display: none; }
    .hero { padding: 60px 24px; }
    .section { padding: 60px 24px; }
    .how-grid { grid-template-columns: 1fr; }
    .stats-inner { grid-template-columns: repeat(2, 1fr); }
    footer { padding: 24px; }
  }
</style>
</head>
<body>
<div class="noise"></div>
<div class="content">

<nav>
  <div class="logo">AiPay<span>Gent</span></div>
  <div class="nav-links">
    <a href="#services">Services</a>
    <a href="#how">Protocol</a>
    <a href="#demo">Try Free</a>
    <a href="https://api.aipaygent.xyz/discover">API</a>
    <a href="https://api.aipaygent.xyz/openapi.json">OpenAPI</a>
  </div>
  <div class="status-badge"><div class="dot"></div>LIVE · x402 ON BASE</div>
</nav>

<section class="hero">
  <div class="tag fade-up">x402 Native Resource Server</div>
  <h1 class="fade-up delay-1">
    AI Services<br>
    <span class="accent">Pay Per Call.</span><br>
    <span class="dim">No Keys. No Auth.</span>
  </h1>
  <p class="hero-sub fade-up delay-2">
    Claude-powered API endpoints for autonomous agents. Research, write, analyze, translate, generate code — pay only for what you use in USDC on Base.
  </p>
  <div class="hero-actions fade-up delay-3">
    <a href="https://api.aipaygent.xyz/discover" class="btn btn-primary">→ Discover API</a>
    <a href="#services" class="btn btn-ghost">View Services</a>
  </div>
</section>

<div class="ticker">
  <div class="ticker-inner">
    <div class="ticker-item"><span>/research</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/summarize</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/analyze</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/translate</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/social</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/write</span><span class="sep">·</span><span class="price">$0.05</span></div>
    <div class="ticker-item"><span>/code</span><span class="sep">·</span><span class="price">$0.05</span></div>
    <div class="ticker-item"><span>/research</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/summarize</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/analyze</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/translate</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/social</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/write</span><span class="sep">·</span><span class="price">$0.05</span></div>
    <div class="ticker-item"><span>/code</span><span class="sep">·</span><span class="price">$0.05</span></div>
    <div class="ticker-item"><span>/extract</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/qa</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/classify</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/sentiment</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/keywords</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/compare</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/transform</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/chat</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/batch</span><span class="sep">·</span><span class="price">$0.10</span></div>
    <div class="ticker-item"><span>/plan</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/decide</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/email</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/sql</span><span class="sep">·</span><span class="price">$0.05</span></div>
    <div class="ticker-item"><span>/proofread</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/explain</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/questions</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/outline</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/mock</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/regex</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/preview</span><span class="sep">·</span><span class="price">FREE</span></div>
    <div class="ticker-item"><span>/research</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/summarize</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/analyze</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/translate</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/social</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/write</span><span class="sep">·</span><span class="price">$0.05</span></div>
    <div class="ticker-item"><span>/code</span><span class="sep">·</span><span class="price">$0.05</span></div>
    <div class="ticker-item"><span>/sentiment</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/keywords</span><span class="sep">·</span><span class="price">$0.01</span></div>
    <div class="ticker-item"><span>/compare</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/transform</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/chat</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/batch</span><span class="sep">·</span><span class="price">$0.10</span></div>
    <div class="ticker-item"><span>/plan</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/decide</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/email</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/sql</span><span class="sep">·</span><span class="price">$0.05</span></div>
    <div class="ticker-item"><span>/proofread</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/explain</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/questions</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/outline</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/mock</span><span class="sep">·</span><span class="price">$0.03</span></div>
    <div class="ticker-item"><span>/regex</span><span class="sep">·</span><span class="price">$0.02</span></div>
    <div class="ticker-item"><span>/preview</span><span class="sep">·</span><span class="price">FREE</span></div>
  </div>
</div>

<section class="section" id="services">
  <div class="section-header">
    <span class="section-title">// Available Endpoints</span>
    <div class="section-line"></div>
  </div>
  <div class="services-grid">
    <div class="service-card">
      <div class="service-endpoint">POST /research</div>
      <div class="service-desc">Research any topic. Returns structured summary, key points, and sources.</div>
      <div class="service-price">$0.01 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /summarize</div>
      <div class="service-desc">Compress long text into key points. Short, medium, or detailed output.</div>
      <div class="service-price">$0.01 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /analyze</div>
      <div class="service-desc">Deep analysis of any content. Returns structured insights and observations.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /translate</div>
      <div class="service-desc">Translate text to any language. Claude handles context and nuance.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /social</div>
      <div class="service-desc">Platform-optimized posts for Twitter, LinkedIn, Instagram and more.</div>
      <div class="service-price">$0.03 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /write</div>
      <div class="service-desc">Articles, copy, and content written to your exact specification.</div>
      <div class="service-price">$0.05 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /code</div>
      <div class="service-desc">Generate production-ready code in any language from a description.</div>
      <div class="service-price">$0.05 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /extract</div>
      <div class="service-desc">Pull structured JSON from any text. Define fields or schema — get clean data back.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /qa</div>
      <div class="service-desc">Q&A over a document. Answer + confidence + source quote. Plug into any RAG pipeline.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /classify</div>
      <div class="service-desc">Classify text into your own categories with per-category confidence scores.</div>
      <div class="service-price">$0.01 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /sentiment</div>
      <div class="service-desc">Polarity, score, emotions, confidence, and key sentiment-driving phrases.</div>
      <div class="service-price">$0.01 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /keywords</div>
      <div class="service-desc">Extract keywords, topics, tags, and detected language from any text.</div>
      <div class="service-price">$0.01 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /compare</div>
      <div class="service-desc">Compare two texts — similarities, differences, similarity score, recommendation.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /transform</div>
      <div class="service-desc">Transform text with any instruction — rewrite, reformat, expand, condense, change tone.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /chat</div>
      <div class="service-desc">Stateless multi-turn chat. Send full message history, receive Claude reply. Custom system prompt supported.</div>
      <div class="service-price">$0.03 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /plan</div>
      <div class="service-desc">Step-by-step action plan for any goal. Includes effort estimate and the single most important first action.</div>
      <div class="service-price">$0.03 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /decide</div>
      <div class="service-desc">Decision framework with pros, cons, risks, recommendation, and confidence score.</div>
      <div class="service-price">$0.03 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /email</div>
      <div class="service-desc">Compose professional emails. Specify purpose, tone, recipient, and length — get subject + body.</div>
      <div class="service-price">$0.03 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /sql</div>
      <div class="service-desc">Natural language to SQL. Describe what you want, get a query with explanation. Supports all major dialects.</div>
      <div class="service-price">$0.05 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /proofread</div>
      <div class="service-desc">Grammar and clarity corrections with tracked changes, writing quality score, and issue list.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /explain</div>
      <div class="service-desc">Explain any concept at beginner, intermediate, or expert level with analogy and key takeaways.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /questions</div>
      <div class="service-desc">Generate FAQ, interview, quiz, or comprehension questions with answers from any content.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /outline</div>
      <div class="service-desc">Hierarchical outline from any topic or document with headings, summaries, and subsections.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /mock</div>
      <div class="service-desc">Generate realistic mock data records. Define schema in plain English — get JSON, CSV, or list.</div>
      <div class="service-price">$0.03 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /regex</div>
      <div class="service-desc">Regex pattern from plain English. Includes explanation, match examples, and non-examples.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /score</div>
      <div class="service-desc">Score content on any custom rubric. Per-criterion scores, strengths, weaknesses, and recommendation.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /timeline</div>
      <div class="service-desc">Extract or reconstruct a chronological timeline from any text. Returns dated events with significance ratings.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /action</div>
      <div class="service-desc">Extract action items, tasks, owners, and due dates from meeting notes or any text.</div>
      <div class="service-price">$0.01 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /pitch</div>
      <div class="service-desc">Generate a timed elevator pitch — hook, value prop, call to action, and full script. 15s, 30s, or 60s.</div>
      <div class="service-price">$0.03 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /debate</div>
      <div class="service-desc">Arguments for and against any position with strength ratings, verdict, and key nuance.</div>
      <div class="service-price">$0.03 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /headline</div>
      <div class="service-desc">Generate headline variations for any content — clickbait, informative, question, how-to — with a best pick.</div>
      <div class="service-price">$0.01 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /fact</div>
      <div class="service-desc">Extract factual claims from text with verifiability scores, source hints, and confidence ratings.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /rewrite</div>
      <div class="service-desc">Rewrite text for a specific audience, reading level, or brand voice. Tone and style control included.</div>
      <div class="service-price">$0.02 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /tag</div>
      <div class="service-desc">Auto-tag content using your taxonomy or free-form. Returns tags, primary tag, and broad categories.</div>
      <div class="service-price">$0.01 <span>per call</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /batch</div>
      <div class="service-desc">Run up to 5 operations in one payment. Best value for multi-step agent pipelines.</div>
      <div class="service-price">$0.10 <span>up to 5 ops</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /pipeline</div>
      <div class="service-desc">Chain up to 5 operations where each step can reference the previous output using {{prev}}. Sequential agent workflows in one call.</div>
      <div class="service-price">$0.15 <span>up to 5 steps</span></div>
    </div>
    <div class="service-card">
      <div class="service-endpoint">POST /preview</div>
      <div class="service-desc">Free 120-token Claude response. Try before you pay — no wallet needed.</div>
      <div class="service-price" style="color: var(--cyan);">FREE</div>
    </div>
  </div>
</section>

<div class="stats-bar">
  <div class="stats-inner">
    <div class="stat"><span class="stat-val" id="stat-requests">—</span><span class="stat-label">Requests Served</span></div>
    <div class="stat"><span class="stat-val">140+</span><span class="stat-label">Endpoints</span></div>
    <div class="stat"><span class="stat-val">x402</span><span class="stat-label">Protocol</span></div>
    <div class="stat"><span class="stat-val" id="stat-earned">—</span><span class="stat-label">USD Earned</span></div>
  </div>
</div>

<section class="section" id="how">
  <div class="section-header">
    <span class="section-title">// How It Works</span>
    <div class="section-line"></div>
  </div>
  <div class="how-grid">
    <div class="steps">
      <div class="step">
        <div class="step-num">01</div>
        <div class="step-content">
          <h3>Discover</h3>
          <p>Hit GET /discover — get a full manifest of services, prices, and payment details. No auth required.</p>
        </div>
      </div>
      <div class="step">
        <div class="step-num">02</div>
        <div class="step-content">
          <h3>Request</h3>
          <p>POST to any endpoint without headers. Receive a 402 Payment Required response with exact payment instructions.</p>
        </div>
      </div>
      <div class="step">
        <div class="step-num">03</div>
        <div class="step-content">
          <h3>Pay</h3>
          <p>Your x402-compatible agent signs a USDC transaction on Base and attaches the payment header.</p>
        </div>
      </div>
      <div class="step">
        <div class="step-num">04</div>
        <div class="step-content">
          <h3>Receive</h3>
          <p>Payment verified on-chain. Claude processes your request and returns the result. Done.</p>
        </div>
      </div>
    </div>
    <div class="code-block">
<span class="c-muted"># 1. Discover available services</span>
<span class="c-key">GET</span> https://api.aipaygent.xyz/discover

<span class="c-muted"># 2. Make a request (returns 402)</span>
<span class="c-key">POST</span> https://api.aipaygent.xyz/research
<span class="c-key">Content-Type:</span> <span class="c-str">application/json</span>

{
  <span class="c-key">"topic"</span>: <span class="c-str">"quantum computing"</span>
}

<span class="c-muted">← HTTP 402 Payment Required
← X-Payment-Info: {
    "scheme": "exact",
    "network": "eip155:8453",
    "amount": "10000",
    "payTo": "0x3E9C..."
  }</span>

<span class="c-muted"># 3. Retry with payment header</span>
<span class="c-key">POST</span> https://api.aipaygent.xyz/research
<span class="c-key">X-Payment:</span> <span class="c-str">&lt;signed-usdc-tx&gt;</span>

<span class="c-muted">← HTTP 200 OK
← { "result": "..." }</span>
    </div>
  </div>
</section>

<section class="section" id="demo">
  <div class="section-header">
    <span class="section-title">// Live Demo — Free</span>
    <div class="section-line"></div>
  </div>
  <div style="max-width:720px;">
    <p style="font-family: IBM Plex Sans, sans-serif; font-size: 0.85rem; color: var(--muted); margin-bottom: 20px; font-weight: 300;">
      Try the API free — no wallet needed. Type any topic and get a real Claude response.
    </p>
    <div style="display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap;">
      <input id="demo-input" type="text" placeholder="e.g. quantum computing breakthroughs" value=""
        style="flex:1; min-width:200px; background:var(--bg2); border:1px solid var(--border); color:var(--text); padding:12px 16px; font-family:IBM Plex Mono,monospace; font-size:0.8rem; outline:none;">
      <button onclick="runDemo()" class="btn btn-primary" style="white-space:nowrap;">→ Try Free</button>
    </div>
    <div id="demo-output" style="display:none; background:var(--bg2); border:1px solid var(--border); padding:24px; font-size:0.82rem; line-height:1.8; color:var(--text);"></div>
    <div id="demo-note" style="display:none; margin-top:10px; font-size:0.7rem; color:var(--muted); letter-spacing:0.05em;"></div>
  </div>
</section>

<footer>
  <div class="footer-left">
    <strong style="color: var(--green);">AiPayGent</strong> · Built on
    <a href="https://x402.org" target="_blank">x402 protocol</a> ·
    Powered by Claude
  </div>
  <div class="footer-right">
    <div class="network-badge"><div class="dot"></div>BASE MAINNET · x402 PROTOCOL</div>
    <div style="margin-top: 8px;">api.aipaygent.xyz</div>
  </div>
</footer>

<script>
// Live stats
fetch('/stats').then(r=>r.json()).then(d=>{
  var req = document.getElementById('stat-requests');
  var earn = document.getElementById('stat-earned');
  if(req) req.textContent = d.total_requests || '0';
  if(earn) earn.textContent = '$' + (d.total_earned_usd || 0).toFixed(4);
}).catch(()=>{});

// Free demo
function runDemo() {
  var input = document.getElementById('demo-input');
  var out = document.getElementById('demo-output');
  var note = document.getElementById('demo-note');
  var btn = document.querySelector('[onclick="runDemo()"]');
  var topic = input.value.trim() || 'x402 payment protocol for AI agents';
  btn.textContent = '...';
  btn.disabled = true;
  out.style.display = 'none';
  note.style.display = 'none';
  fetch('/preview', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({topic: topic})
  }).then(r=>r.json()).then(d=>{
    out.textContent = d.result;
    out.style.display = 'block';
    note.textContent = d.note;
    note.style.display = 'block';
    btn.textContent = '→ Try Free';
    btn.disabled = false;
  }).catch(e=>{
    out.textContent = 'Error: ' + e.message;
    out.style.display = 'block';
    btn.textContent = '→ Try Free';
    btn.disabled = false;
  });
}
</script>

</div>
</body>
</html>'''


@app.route("/")
def landing():
    from flask import make_response
    resp = make_response(render_template_string(LANDING_HTML))
    resp.headers["Link"] = '</llms.txt>; rel="llms-txt"'
    return resp


@app.route("/stats")
def stats():
    if not os.path.exists(PAYMENTS_LOG):
        return jsonify({"total_requests": 0, "total_earned_usd": 0.0, "by_endpoint": {}})
    entries = []
    with open(PAYMENTS_LOG) as f:
        for line in f:
            entries.append(json.loads(line))
    by_endpoint = {}
    for e in entries:
        ep = e["endpoint"]
        by_endpoint.setdefault(ep, {"requests": 0, "earned_usd": 0.0})
        by_endpoint[ep]["requests"] += 1
        by_endpoint[ep]["earned_usd"] += e["amount_usd"]
    return jsonify({
        "total_requests": len(entries),
        "total_earned_usd": round(sum(e["amount_usd"] for e in entries), 4),
        "by_endpoint": by_endpoint,
    })


# ══════════════════════════════════════════════════════════════════════════════
# BLOG — Auto-generated SEO tutorials, indexed by search engines + LLMs
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/blog", methods=["GET"])
def blog_index():
    posts = list_blog_posts()
    items = "".join(
        f'<li style="margin:0.6rem 0"><a href="/blog/{p["slug"]}">{p["title"]}</a> <small style="color:#888">· {p.get("generated_at","")[:10]}</small></li>'
        for p in posts
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGent Blog — AI Agent & API Developer Tutorials</title>
<meta name="description" content="Developer tutorials for building with AiPayGent — 140+ Claude-powered AI API endpoints. Covers AI agents, scraping, x402 payments, real-time data, and more. First 10 calls/day free.">
<link rel="canonical" href="https://api.aipaygent.xyz/blog">
<link rel="alternate" type="application/rss+xml" title="AiPayGent Blog RSS" href="/feed.xml">
<meta property="og:type" content="website">
<meta property="og:title" content="AiPayGent Developer Blog">
<meta property="og:description" content="Tutorials for building AI agents and automations with AiPayGent's 140+ Claude-powered endpoints.">
<meta property="og:url" content="https://api.aipaygent.xyz/blog">
<meta property="og:image" content="https://api.aipaygent.xyz/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps({"@context":"https://schema.org","@type":"Blog","name":"AiPayGent Developer Blog","url":"https://api.aipaygent.xyz/blog","description":"Developer tutorials for AI agent APIs","publisher":{"@type":"Organization","name":"AiPayGent","url":"https://api.aipaygent.xyz"}})}</script>
<style>body{{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6;color:#1a1a1a}}a{{color:#6366f1}}h1{{color:#1e1b4b}}.rss{{float:right;font-size:0.85rem;background:#f4f4f4;padding:4px 10px;border-radius:20px;text-decoration:none;color:#555}}</style>
</head>
<body>
<a class="rss" href="/feed.xml">RSS feed</a>
<h1>AiPayGent Developer Blog</h1>
<p>Tutorials for building AI agents with AiPayGent — 140+ Claude-powered endpoints. <strong>First 10 calls/day free.</strong></p>
<ul style="padding-left:1.2rem">{items}</ul>
<p><a href="https://api.aipaygent.xyz/discover">Browse all 140+ endpoints →</a> · <a href="https://api.aipaygent.xyz/buy-credits">Buy credits ($5+) →</a></p>
</body>
</html>"""
    resp = Response(html, content_type="text/html")
    resp.headers["Link"] = '</feed.xml>; rel="alternate"; type="application/rss+xml"'
    return resp


@app.route("/blog/<slug>", methods=["GET"])
def blog_post(slug):
    post = get_blog_post(slug)
    if not post:
        return jsonify({"error": "post not found"}), 404
    canonical = f"https://api.aipaygent.xyz/blog/{slug}"
    desc = f"{post['title']} — Developer tutorial for AiPayGent, the pay-per-use Claude AI API with 140+ endpoints."
    jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "TechArticle",
        "headline": post['title'],
        "description": desc,
        "url": canonical,
        "datePublished": post.get("generated_at", "")[:10],
        "author": {"@type": "Organization", "name": "AiPayGent"},
        "publisher": {
            "@type": "Organization",
            "name": "AiPayGent",
            "url": "https://api.aipaygent.xyz"
        }
    })
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{post['title']} — AiPayGent</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="{post['title']}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://api.aipaygent.xyz/og-image.png">
<meta property="og:site_name" content="AiPayGent">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{post['title']}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="https://api.aipaygent.xyz/og-image.png">
<script type="application/ld+json">{jsonld}</script>
<style>
body{{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.7;color:#1a1a1a}}
code,pre{{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:0.9em;font-family:monospace}}
pre{{padding:16px;overflow-x:auto;display:block}}a{{color:#6366f1}}h1{{color:#1e1b4b;font-size:1.9rem}}
.nav{{color:#888;margin-bottom:2rem;font-size:0.9rem}}.cta{{background:#f8f7ff;border:1px solid #e0e0ff;border-radius:8px;padding:16px;margin:2rem 0}}
</style>
</head>
<body>
<div class="nav"><a href="/blog">← All posts</a> · <a href="https://api.aipaygent.xyz">AiPayGent API</a> · <a href="/discover">140+ endpoints</a></div>
<h1>{post['title']}</h1>
{post['content']}
<div class="cta">
  <strong>Try it free →</strong> First 10 calls/day free, no credit card. <a href="https://api.aipaygent.xyz/discover">Browse all 140+ endpoints</a> or <a href="https://api.aipaygent.xyz/buy-credits">buy credits ($5+)</a>.
</div>
<p style="color:#888;font-size:0.85rem">Published: {post.get('generated_at','')[:10]} · <a href="/feed.xml">RSS feed</a></p>
</body>
</html>"""
    return Response(html, content_type="text/html")


# ══════════════════════════════════════════════════════════════════════════════
# REFERRAL / AFFILIATE PROGRAM
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/referral/join", methods=["POST"])
def referral_join():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "").strip()
    label = data.get("label", "")
    api_key = data.get("api_key", "")
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400
    result = register_referral_agent(agent_id, label, api_key)
    result["note"] = "Share your referral_url. Earn 10% of every purchase your referrals make, credited to your API key."
    return jsonify(result)


@app.route("/referral/stats/<agent_id>", methods=["GET"])
def referral_stats(agent_id):
    return jsonify(get_referral_stats(agent_id))


@app.route("/referral/leaderboard", methods=["GET"])
def referral_leaderboard():
    limit = min(int(request.args.get("limit", 20)), 100)
    return jsonify({"leaderboard": get_referral_leaderboard(limit), "commission_rate": "10%"})


@app.route("/ref/<agent_id>", methods=["GET"])
def referral_redirect(agent_id):
    """Short referral redirect — /ref/my-agent → home with ?ref=my-agent cookie set."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
    try:
        record_click(agent_id, ip, "/ref/" + agent_id, request.headers.get("User-Agent", ""))
    except Exception:
        pass
    dest = request.args.get("to", "/buy-credits") + f"?ref={agent_id}"
    from flask import redirect
    return redirect(dest, code=302)


# ══════════════════════════════════════════════════════════════════════════════
# DISCOVERY ENGINE — outreach status + manual trigger
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/discovery/status", methods=["GET"])
def discovery_engine_status():
    log = get_outreach_log(50)
    posts = list_blog_posts()
    return jsonify({"outreach_log": log, "blog_posts": len(posts), "posts": posts})


@app.route("/discovery/trigger", methods=["POST"])
def discovery_trigger():
    data = request.get_json() or {}
    job = data.get("job", data.get("task", "hourly"))
    import threading as _t
    if job == "daily":
        _t.Thread(target=lambda: run_daily(claude), daemon=True).start()
    elif job == "weekly":
        _t.Thread(target=lambda: run_weekly(claude), daemon=True).start()
    elif job == "blog":
        _t.Thread(target=lambda: generate_all_blog_posts(claude, force=True), daemon=True).start()
    elif job == "canary":
        result = run_canary()
        return jsonify({"job": "canary", "result": result})
    elif job == "maintenance":
        result = run_maintenance()
        return jsonify({"job": "maintenance", "result": result})
    elif job == "economy":
        _t.Thread(target=_run_agent_economy, daemon=True).start()
        return jsonify({"job": "economy", "note": "Running in background"})
    else:
        _t.Thread(target=lambda: run_hourly(claude), daemon=True).start()
    return jsonify({"triggered": job, "note": "Running in background"})


# ══════════════════════════════════════════════════════════════════════════════
# FREE DAILY TIER STATUS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/free-tier/status", methods=["GET"])
def free_tier_status():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
    return jsonify(get_free_tier_status(ip))


# ══════════════════════════════════════════════════════════════════════════════
# AGENT REPUTATION + LEADERBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/agents/leaderboard", methods=["GET"])
def agents_leaderboard():
    limit = min(int(request.args.get("limit", 20)), 100)
    board = get_leaderboard(limit)
    return jsonify({"leaderboard": board, "count": len(board),
                    "scoring": "task_completions×3 + knowledge_contributions×1.5 + upvotes×0.5"})


@app.route("/agent/reputation/<agent_id>", methods=["GET"])
def agent_reputation_route(agent_id):
    return jsonify(get_reputation(agent_id))


# ══════════════════════════════════════════════════════════════════════════════
# TASK SUBSCRIPTIONS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/task/subscribe", methods=["POST"])
def task_subscribe():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "")
    callback_url = data.get("callback_url", "")
    skills = data.get("skills", [])
    if not agent_id or not callback_url:
        return jsonify({"error": "agent_id and callback_url required"}), 400
    result = subscribe_tasks(agent_id, skills, callback_url)
    return jsonify(result)


@app.route("/task/subscription/<agent_id>", methods=["GET"])
def task_subscription_status(agent_id):
    sub = get_task_subscribers(agent_id)
    if not sub:
        return jsonify({"error": "no subscription found", "agent_id": agent_id}), 404
    return jsonify(sub)


# ══════════════════════════════════════════════════════════════════════════════
# ASYNC JOBS + WEBHOOK CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

# Mapping of endpoint name -> handler function (for async execution)
_ASYNC_HANDLERS = {}  # populated after route definitions (see bottom of routes section)


@app.route("/async/submit", methods=["POST"])
def async_submit():
    data = request.get_json() or {}
    endpoint = data.get("endpoint", "").lstrip("/")
    payload = data.get("payload", {})
    callback_url = data.get("callback_url")
    if not endpoint or not payload:
        return jsonify({"error": "endpoint and payload required"}), 400
    if endpoint not in _ASYNC_HANDLERS:
        available = list(_ASYNC_HANDLERS.keys())
        return jsonify({"error": "unsupported async endpoint", "available": available}), 400
    job_id = submit_job(endpoint, payload, callback_url)
    run_job_async(job_id, _ASYNC_HANDLERS[endpoint])
    return jsonify({
        "job_id": job_id,
        "status": "pending",
        "status_url": f"https://api.aipaygent.xyz/async/status/{job_id}",
        "callback_url": callback_url,
        "note": "Poll status_url or wait for callback POST",
    })


@app.route("/async/status/<job_id>", methods=["GET"])
def async_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


# ══════════════════════════════════════════════════════════════════════════════
# FILE STORAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/files/upload", methods=["POST"])
def files_upload():
    agent_id = request.args.get("agent_id") or (request.get_json() or {}).get("agent_id", "anonymous")
    if "file" in request.files:
        f = request.files["file"]
        data = f.read()
        filename = f.filename or "upload"
        content_type = f.content_type or "application/octet-stream"
    else:
        body = request.get_json() or {}
        b64 = body.get("base64_data", "")
        filename = body.get("filename", "file.bin")
        content_type = body.get("content_type", "application/octet-stream")
        try:
            data = base64.b64decode(b64)
        except Exception:
            return jsonify({"error": "invalid base64_data"}), 400
    try:
        result = save_file(agent_id, filename, content_type, data)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 413


@app.route("/files/<file_id>", methods=["GET"])
def files_get(file_id):
    meta, data = get_file(file_id)
    if meta is None:
        return jsonify({"error": "file not found"}), 404
    return Response(data, content_type=meta["content_type"],
                    headers={"Content-Disposition": f"inline; filename=\"{meta['filename']}\""})


@app.route("/files/<file_id>", methods=["DELETE"])
def files_delete(file_id):
    agent_id = (request.get_json() or {}).get("agent_id", "")
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400
    ok = delete_file(file_id, agent_id)
    return jsonify({"deleted": ok, "file_id": file_id})


@app.route("/files/list/<agent_id>", methods=["GET"])
def files_list(agent_id):
    files = list_files(agent_id)
    return jsonify({"files": files, "count": len(files), "agent_id": agent_id})


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK RELAY
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/webhooks/create", methods=["POST"])
def webhooks_create():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "anonymous")
    label = data.get("label")
    result = create_webhook(agent_id, label)
    return jsonify(result)


@app.route("/webhooks/<webhook_id>/receive", methods=["GET", "POST", "PUT", "PATCH"])
def webhooks_receive(webhook_id):
    body = request.get_data(as_text=True)
    headers = dict(request.headers)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
    result = receive_webhook_event(webhook_id, request.method, headers, body, ip)
    if result is None:
        return jsonify({"error": "webhook not found"}), 404
    return jsonify({"received": True, "event_id": result["event_id"]})


@app.route("/webhooks/<webhook_id>/events", methods=["GET"])
def webhooks_events(webhook_id):
    hook = get_webhook(webhook_id)
    if not hook:
        return jsonify({"error": "webhook not found"}), 404
    limit = min(int(request.args.get("limit", 50)), 200)
    events = get_webhook_events(webhook_id, limit)
    return jsonify({
        "webhook_id": webhook_id,
        "events": events,
        "count": len(events),
        "total_received": hook["event_count"],
    })


@app.route("/webhooks/list/<agent_id>", methods=["GET"])
def webhooks_list(agent_id):
    hooks = list_webhooks(agent_id)
    return jsonify({"webhooks": hooks, "count": len(hooks)})


# ══════════════════════════════════════════════════════════════════════════════
# FREE DATA — EXPANDED (Wikipedia, arXiv, GitHub, Reddit, YouTube, QR, DNS, etc.)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/data/wikipedia", methods=["GET"])
def data_wikipedia():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q required (search term or article title)"}), 400
    ck = f"wiki:{_hashlib.md5(q.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        # Search for article
        search_resp = _requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + _requests.utils.quote(q),
            headers={"User-Agent": "AiPayGent/2.0 (https://api.aipaygent.xyz)"},
            timeout=8,
        )
        if search_resp.status_code == 404:
            # Try search API
            s = _requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": q, "limit": 1, "format": "json"},
                headers={"User-Agent": "AiPayGent/2.0"},
                timeout=8,
            ).json()
            if s[1]:
                title = s[1][0]
                search_resp = _requests.get(
                    "https://en.wikipedia.org/api/rest_v1/page/summary/" + _requests.utils.quote(title),
                    headers={"User-Agent": "AiPayGent/2.0"},
                    timeout=8,
                )
            else:
                return jsonify({"error": "article not found", "query": q}), 404
        d = search_resp.json()
        result = {
            "title": d.get("title", ""),
            "summary": d.get("extract", ""),
            "url": d.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "thumbnail": d.get("thumbnail", {}).get("source", "") if d.get("thumbnail") else "",
            "description": d.get("description", ""),
            "query": q,
        }
        _cache_set(ck, result, 3600)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "wikipedia_failed", "message": str(e)}), 502


@app.route("/data/arxiv", methods=["GET"])
def data_arxiv():
    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 5)), 20)
    if not q:
        return jsonify({"error": "q required"}), 400
    ck = f"arxiv:{_hashlib.md5(f'{q}{limit}'.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{q}", "max_results": limit, "sortBy": "relevance"},
            timeout=12,
        )
        feed = feedparser.parse(resp.text)
        papers = []
        for entry in feed.entries[:limit]:
            papers.append({
                "title": entry.get("title", "").replace("\n", " "),
                "summary": (entry.get("summary", "")[:500] + "...").replace("\n", " "),
                "authors": [a.get("name", "") for a in entry.get("authors", [])],
                "published": entry.get("published", ""),
                "url": entry.get("link", ""),
                "arxiv_id": entry.get("id", "").split("/abs/")[-1],
            })
        result = {"query": q, "papers": papers, "count": len(papers)}
        _cache_set(ck, result, 1800)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "arxiv_failed", "message": str(e)}), 502


@app.route("/data/github/trending", methods=["GET"])
def data_github_trending():
    lang = request.args.get("lang", "").lower()
    since = request.args.get("since", "daily")
    ck = f"gh_trend:{lang}:{since}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        url = "https://github.com/trending"
        if lang:
            url += f"/{lang}"
        resp = _requests.get(url, params={"since": since},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        repos = []
        for article in soup.select("article.Box-row")[:25]:
            h2 = article.select_one("h2 a")
            if not h2:
                continue
            desc_el = article.select_one("p")
            stars_el = article.select_one("a[href*='/stargazers']")
            lang_el = article.select_one("[itemprop='programmingLanguage']")
            repos.append({
                "repo": h2.get("href", "").lstrip("/"),
                "url": "https://github.com" + h2.get("href", ""),
                "description": desc_el.get_text(strip=True) if desc_el else "",
                "stars": stars_el.get_text(strip=True) if stars_el else "",
                "language": lang_el.get_text(strip=True) if lang_el else "",
            })
        result = {"language": lang or "all", "since": since, "repos": repos, "count": len(repos)}
        _cache_set(ck, result, 3600)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "github_trending_failed", "message": str(e)}), 502


@app.route("/data/reddit", methods=["GET"])
def data_reddit():
    q = request.args.get("q", "").strip()
    sub = request.args.get("sub", "")
    sort = request.args.get("sort", "hot")
    limit = min(int(request.args.get("limit", 10)), 25)
    if not q and not sub:
        return jsonify({"error": "q (search query) or sub (subreddit) required"}), 400
    ck = f"reddit:{_hashlib.md5(f'{q}{sub}{sort}{limit}'.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        if q:
            url = f"https://www.reddit.com/search.json"
            params = {"q": q, "sort": sort, "limit": limit}
            if sub:
                params["restrict_sr"] = "true"
                url = f"https://www.reddit.com/r/{sub}/search.json"
        else:
            url = f"https://www.reddit.com/r/{sub}/{sort}.json"
            params = {"limit": limit}
        resp = _requests.get(url, params=params,
                             headers={"User-Agent": "AiPayGent/2.0 bot"}, timeout=10)
        data = resp.json()
        posts = []
        for child in data.get("data", {}).get("children", [])[:limit]:
            p = child.get("data", {})
            posts.append({
                "title": p.get("title", ""),
                "subreddit": p.get("subreddit", ""),
                "url": "https://reddit.com" + p.get("permalink", ""),
                "external_url": p.get("url", ""),
                "score": p.get("score", 0),
                "comments": p.get("num_comments", 0),
                "author": p.get("author", ""),
                "created": p.get("created_utc", 0),
            })
        result = {"query": q, "subreddit": sub, "posts": posts, "count": len(posts)}
        _cache_set(ck, result, 600)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "reddit_failed", "message": str(e)}), 502


@app.route("/data/youtube/transcript", methods=["GET"])
def data_youtube_transcript():
    video_id = request.args.get("video_id", "").strip()
    lang = request.args.get("lang", "en")
    if not video_id:
        return jsonify({"error": "video_id required (e.g. dQw4w9WgXcQ)"}), 400
    ck = f"yt_transcript:{video_id}:{lang}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang, "en"])
        full_text = " ".join(t["text"] for t in transcript_list)
        result = {
            "video_id": video_id,
            "language": lang,
            "transcript": transcript_list[:200],  # first 200 segments
            "full_text": full_text[:10000],
            "word_count": len(full_text.split()),
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }
        _cache_set(ck, result, 86400)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "transcript_failed", "message": str(e),
                       "hint": "Video may have no captions or be age-restricted"}), 502


@app.route("/data/qr", methods=["GET"])
def data_qr():
    text = request.args.get("text", "").strip()
    size = min(int(request.args.get("size", 200)), 600)
    if not text:
        return jsonify({"error": "text required"}), 400
    ck = f"qr:{_hashlib.md5(f'{text}{size}'.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        qr = qrcode.QRCode(box_size=max(1, size // 33), border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        result = {
            "text": text,
            "size": size,
            "format": "PNG",
            "base64": b64,
            "data_url": f"data:image/png;base64,{b64}",
        }
        _cache_set(ck, result, 86400)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "qr_failed", "message": str(e)}), 500


@app.route("/data/dns", methods=["GET"])
def data_dns():
    domain = request.args.get("domain", "").strip().rstrip("/")
    if not domain:
        return jsonify({"error": "domain required"}), 400
    ck = f"dns:{domain}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        import socket as _sock
        records = {}
        # A / IPv4
        try:
            ipv4 = [r[4][0] for r in _sock.getaddrinfo(domain, None, _sock.AF_INET)]
            records["A"] = list(set(ipv4))
        except Exception:
            records["A"] = []
        # AAAA / IPv6
        try:
            ipv6 = [r[4][0] for r in _sock.getaddrinfo(domain, None, _sock.AF_INET6)]
            records["AAAA"] = list(set(ipv6))
        except Exception:
            records["AAAA"] = []
        # Reverse lookup for first A record
        reverse = ""
        if records["A"]:
            try:
                reverse = _sock.gethostbyaddr(records["A"][0])[0]
            except Exception:
                pass
        result = {
            "domain": domain,
            "records": records,
            "reverse_hostname": reverse,
        }
        _cache_set(ck, result, 300)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "dns_failed", "message": str(e)}), 502


@app.route("/data/validate/email", methods=["GET"])
def data_validate_email():
    email = request.args.get("email", "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400
    import re as _email_re
    pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
    fmt_valid = bool(_email_re.match(pattern, email))
    domain = email.split("@")[-1] if "@" in email else ""
    mx_valid = False
    if fmt_valid and domain:
        try:
            import socket as _s
            _s.getaddrinfo(domain, None)
            mx_valid = True
        except Exception:
            pass
    disposable_domains = {"mailinator.com", "guerrillamail.com", "tempmail.com",
                          "throwaway.email", "yopmail.com", "trashmail.com"}
    result = {
        "email": email,
        "format_valid": fmt_valid,
        "domain_reachable": mx_valid,
        "possibly_disposable": domain in disposable_domains,
        "domain": domain,
    }
    return jsonify(result)


@app.route("/data/validate/url", methods=["GET"])
def data_validate_url():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = _requests.head(url, timeout=8, allow_redirects=True,
                              headers={"User-Agent": "AiPayGent/2.0"})
        result = {
            "url": url,
            "reachable": True,
            "status_code": resp.status_code,
            "final_url": resp.url,
            "redirected": resp.url != url,
            "content_type": resp.headers.get("Content-Type", ""),
        }
    except Exception as e:
        result = {"url": url, "reachable": False, "error": str(e)}
    return jsonify(result)


@app.route("/data/random/name", methods=["GET"])
def data_random_name():
    count = min(int(request.args.get("count", 1)), 20)
    nat = request.args.get("nationality", "us")
    try:
        resp = _requests.get(
            "https://randomuser.me/api/",
            params={"results": count, "nat": nat, "inc": "name,email,location,phone"},
            timeout=8,
        )
        people = []
        for u in resp.json().get("results", []):
            n = u.get("name", {})
            loc = u.get("location", {})
            people.append({
                "name": f"{n.get('first', '')} {n.get('last', '')}".strip(),
                "email": u.get("email", ""),
                "phone": u.get("phone", ""),
                "city": loc.get("city", ""),
                "country": loc.get("country", ""),
            })
        return jsonify({"people": people, "count": len(people)})
    except Exception as e:
        return jsonify({"error": "random_name_failed", "message": str(e)}), 502


@app.route("/data/color", methods=["GET"])
def data_color():
    hex_str = request.args.get("hex", "").lstrip("#").strip()
    if not hex_str or len(hex_str) not in (3, 6):
        return jsonify({"error": "hex required (e.g. ?hex=ff5733 or ?hex=f53)"}), 400
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    try:
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        comp_h = (h + 0.5) % 1.0
        cr, cg, cb = colorsys.hls_to_rgb(comp_h, l, s)
        comp_hex = "{:02x}{:02x}{:02x}".format(int(cr * 255), int(cg * 255), int(cb * 255))
        # Brightness
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        result = {
            "hex": f"#{hex_str.upper()}",
            "rgb": {"r": r, "g": g, "b": b},
            "hsl": {"h": round(h * 360), "s": round(s * 100), "l": round(l * 100)},
            "complementary": f"#{comp_hex.upper()}",
            "brightness": round(brightness),
            "is_dark": brightness < 128,
            "css": f"rgb({r}, {g}, {b})",
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "color_failed", "message": str(e)}), 400


@app.route("/data/screenshot", methods=["GET"])
def data_screenshot():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    ck = f"screenshot:{_hashlib.md5(url.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        # Use thum.io free screenshot API (no key needed)
        screenshot_url = f"https://image.thum.io/get/width/1280/crop/800/{url}"
        result = {
            "url": url,
            "screenshot_url": screenshot_url,
            "note": "Visit screenshot_url directly to render. Cached 24h by thum.io.",
        }
        _cache_set(ck, result, 3600)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "screenshot_failed", "message": str(e)}), 502


# ══════════════════════════════════════════════════════════════════════════════
# REGISTER ASYNC HANDLERS (after all route functions defined)
# ══════════════════════════════════════════════════════════════════════════════

def _async_research(payload):
    from flask import current_app
    topic = payload.get("topic", "")
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=800,
        messages=[{"role": "user", "content": f"Research this topic and return a JSON object with keys: summary, key_points (list), sources_to_check (list). Topic: {topic}"}]
    )
    return parse_json_from_claude(msg.content[0].text) or {"result": msg.content[0].text}


def _async_write(payload):
    spec = payload.get("spec", "")
    type_ = payload.get("type", "article")
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=1500,
        messages=[{"role": "user", "content": f"Write a {type_} based on this specification. Return a JSON object with: title, content, word_count. Spec: {spec}"}]
    )
    return parse_json_from_claude(msg.content[0].text) or {"content": msg.content[0].text}


def _async_analyze(payload):
    content = payload.get("content", "")
    question = payload.get("question", "Analyze this content")
    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=800,
        messages=[{"role": "user", "content": f"Analyze this content and answer the question. Return JSON with: conclusion, key_findings (list), sentiment, confidence. Content: {content}\nQuestion: {question}"}]
    )
    return parse_json_from_claude(msg.content[0].text) or {"result": msg.content[0].text}


_ASYNC_HANDLERS.update({
    "research": _async_research,
    "write": _async_write,
    "analyze": _async_analyze,
})


@app.route("/discover")
def discover():
    base_url = "https://api.aipaygent.xyz"
    return jsonify({
        "name": "AiPayGent",
        "description": "Pay-per-use Claude AI API. No accounts, no API keys. Pay USDC on Base via x402 — get results instantly.",
        "url": base_url,
        "openapi": f"{base_url}/openapi.json",
        "llms_txt": f"{base_url}/llms.txt",
        "preview": f"{base_url}/preview",
        "wallet": WALLET_ADDRESS,
        "network": EVM_NETWORK,
        "payment_scheme": "x402/exact",
        "usdc_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "services": [
            # --- Web Intelligence (featured) ---
            {"endpoint": "/scrape", "method": "POST", "price_usd": 0.01, "input": {"url": "string"}, "output": {"url": "string", "text": "string", "word_count": "int"}, "description": "Fetch any URL, return clean markdown text"},
            {"endpoint": "/search", "method": "POST", "price_usd": 0.01, "input": {"query": "string", "n": "int (default 5, max 10)"}, "output": {"query": "string", "results": [{"title": "string", "url": "string", "snippet": "string"}]}, "description": "DuckDuckGo web search, returns top N results"},
            {"endpoint": "/extract", "method": "POST", "price_usd": 0.02, "input": {"url": "string OR text: string", "schema": {"field": "description"}, "fields": ["field1"]}, "description": "Extract structured data from URL or text using a schema"},
            {"endpoint": "/research", "method": "POST", "price_usd": 0.15, "input": {"question": "string"}, "output": {"question": "string", "answer": "string", "sources": [{"title": "string", "url": "string"}]}, "description": "Deep research: search + scrape + AI synthesis with citations"},
            # --- AI Processing ---
            {"endpoint": "/summarize", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "length": "short|medium|detailed"}, "description": "Summarize long text into key points"},
            {"endpoint": "/analyze", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "question": "string"}, "description": "Analyze data or text, returns structured insights"},
            {"endpoint": "/translate", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "language": "string"}, "description": "Translate text to any language"},
            {"endpoint": "/social", "method": "POST", "price_usd": 0.03, "input": {"topic": "string", "platforms": ["twitter", "linkedin", "instagram"], "tone": "string"}, "description": "Generate platform-optimized social media posts"},
            {"endpoint": "/write", "method": "POST", "price_usd": 0.05, "input": {"spec": "string", "type": "article|post|copy"}, "description": "Write articles, copy, or content to spec"},
            {"endpoint": "/code", "method": "POST", "price_usd": 0.05, "input": {"description": "string", "language": "string"}, "description": "Generate code in any language"},
            {"endpoint": "/extract", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "fields": ["field1", "field2"], "schema": "optional"}, "description": "Extract structured data from unstructured text — define fields or a schema"},
            {"endpoint": "/qa", "method": "POST", "price_usd": 0.02, "input": {"context": "string", "question": "string"}, "description": "Q&A over a document — answer + confidence + source quote. Core RAG building block."},
            {"endpoint": "/classify", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "categories": ["cat1", "cat2"]}, "description": "Classify text into your defined categories with per-category confidence scores"},
            {"endpoint": "/sentiment", "method": "POST", "price_usd": 0.01, "input": {"text": "string"}, "description": "Deep sentiment — polarity, score, emotions, confidence, key phrases"},
            {"endpoint": "/keywords", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "max_keywords": 10}, "description": "Extract keywords, topics, tags from any text"},
            {"endpoint": "/compare", "method": "POST", "price_usd": 0.02, "input": {"text_a": "string", "text_b": "string", "focus": "optional"}, "description": "Compare two texts — similarities, differences, similarity score, recommendation"},
            {"endpoint": "/transform", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "instruction": "string"}, "description": "Transform text with any instruction — rewrite, reformat, expand, condense, translate style"},
            {"endpoint": "/chat", "method": "POST", "price_usd": 0.03, "input": {"messages": [{"role": "user", "content": "string"}], "system": "optional"}, "description": "Stateless multi-turn chat — send full message history, get Claude reply"},
            {"endpoint": "/batch", "method": "POST", "price_usd": 0.10, "input": {"operations": [{"endpoint": "string", "input": {}}]}, "description": "Run up to 5 operations in one payment — best value for multi-step pipelines"},
            {"endpoint": "/plan", "method": "POST", "price_usd": 0.03, "input": {"goal": "string", "context": "optional", "steps": 7}, "description": "Step-by-step action plan with effort estimate and first action"},
            {"endpoint": "/decide", "method": "POST", "price_usd": 0.03, "input": {"decision": "string", "options": ["A", "B"], "criteria": "optional"}, "description": "Decision framework — pros, cons, risks, recommendation, confidence"},
            {"endpoint": "/proofread", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "style": "professional"}, "description": "Grammar/spelling/clarity corrections with tracked issues and writing score"},
            {"endpoint": "/explain", "method": "POST", "price_usd": 0.02, "input": {"concept": "string", "level": "beginner|intermediate|expert", "analogy": True}, "description": "Explain any concept with analogy, key points, common misconceptions"},
            {"endpoint": "/questions", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "type": "faq|interview|quiz|comprehension", "count": 5}, "description": "Generate questions + answers from any content"},
            {"endpoint": "/outline", "method": "POST", "price_usd": 0.02, "input": {"topic": "string", "depth": 2, "sections": 6}, "description": "Hierarchical outline with headings, summaries, and subsections"},
            {"endpoint": "/email", "method": "POST", "price_usd": 0.03, "input": {"purpose": "string", "tone": "professional", "recipient": "optional", "length": "short|medium|long"}, "description": "Compose professional emails with subject and body"},
            {"endpoint": "/sql", "method": "POST", "price_usd": 0.05, "input": {"description": "string", "dialect": "postgresql", "schema": "optional"}, "description": "Natural language to SQL — query + explanation + notes"},
            {"endpoint": "/regex", "method": "POST", "price_usd": 0.02, "input": {"description": "string", "language": "python", "flags": "optional"}, "description": "Regex pattern from description with examples and non-examples"},
            {"endpoint": "/mock", "method": "POST", "price_usd": 0.03, "input": {"description": "string", "count": 5, "format": "json|csv|list"}, "description": "Generate realistic mock data records with schema"},
            {"endpoint": "/preview", "method": "POST", "price_usd": 0.00, "input": {"topic": "string"}, "description": "Free 120-token Claude preview — no payment required"},
            {"endpoint": "/score", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "criteria": ["clarity", "accuracy"], "scale": 10}, "description": "Score content quality on any custom rubric — per-criterion scores + strengths/weaknesses"},
            {"endpoint": "/timeline", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "direction": "chronological"}, "description": "Extract or reconstruct a chronological timeline of events from any text"},
            {"endpoint": "/action", "method": "POST", "price_usd": 0.01, "input": {"text": "string"}, "description": "Extract action items, tasks, owners, and due dates from meeting notes or any text"},
            {"endpoint": "/pitch", "method": "POST", "price_usd": 0.03, "input": {"product": "string", "audience": "string", "length": "15s|30s|60s"}, "description": "Generate elevator pitch — hook, value prop, call to action, full script"},
            {"endpoint": "/debate", "method": "POST", "price_usd": 0.03, "input": {"topic": "string", "perspective": "balanced|for|against"}, "description": "Arguments for and against any position with strength ratings and verdict"},
            {"endpoint": "/headline", "method": "POST", "price_usd": 0.01, "input": {"content": "string", "count": 5, "style": "engaging|clickbait|informative"}, "description": "Generate compelling headlines and titles for any content"},
            {"endpoint": "/fact", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "count": 10}, "description": "Extract factual claims from text with verifiability scores and source hints"},
            {"endpoint": "/rewrite", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "audience": "string", "tone": "string"}, "description": "Rewrite text for a specific audience, reading level, or brand voice"},
            {"endpoint": "/tag", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "taxonomy": ["optional", "tags"], "max_tags": 10}, "description": "Auto-tag content using a provided taxonomy or free-form tagging"},
            {"endpoint": "/pipeline", "method": "POST", "price_usd": 0.15, "input": {"steps": [{"endpoint": "string", "input": {}}]}, "description": "Chain up to 5 operations where each step can use {{prev}} to reference previous output"},
            {"endpoint": "/vision", "method": "POST", "price_usd": 0.05, "input": {"url": "image_url", "question": "optional"}, "description": "Analyze any image URL with Claude Vision — describe, extract text, answer questions"},
            {"endpoint": "/rag", "method": "POST", "price_usd": 0.05, "input": {"documents": "text (use --- to separate docs)", "query": "string"}, "description": "Grounded Q&A — answer questions using only your provided documents, with citations"},
            {"endpoint": "/diagram", "method": "POST", "price_usd": 0.03, "input": {"description": "string", "type": "flowchart|sequence|erd|gantt|mindmap"}, "description": "Generate Mermaid diagrams from a plain English description"},
            {"endpoint": "/json-schema", "method": "POST", "price_usd": 0.02, "input": {"description": "string", "example": "optional JSON example"}, "description": "Generate JSON Schema (draft-07) from a plain English description of your data"},
            {"endpoint": "/test-cases", "method": "POST", "price_usd": 0.03, "input": {"code": "code or description", "language": "python"}, "description": "Generate comprehensive unit test cases with edge cases for any code or feature"},
            {"endpoint": "/workflow", "method": "POST", "price_usd": 0.20, "input": {"goal": "string", "data": "optional context"}, "description": "Multi-step agentic reasoning with Claude Sonnet — breaks down and executes complex goals"},
            {"endpoint": "/memory/set", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "key": "string", "value": "any", "tags": ["optional"]}, "description": "Store persistent memory for any agent — survives across sessions and requests"},
            {"endpoint": "/memory/get", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "key": "string"}, "description": "Retrieve a stored memory by agent_id and key"},
            {"endpoint": "/memory/search", "method": "POST", "price_usd": 0.02, "input": {"agent_id": "string", "query": "string"}, "description": "Search all memories for an agent by keyword"},
            {"endpoint": "/memory/clear", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string"}, "description": "Delete all memories for an agent — use before context reset"},
            {"endpoint": "/api-call", "method": "POST", "price_usd": 0.05, "input": {"api_id": "int from /catalog", "endpoint": "/path", "params": {}, "api_key": "optional", "enrich": False}, "description": "Proxy-call any API in the catalog — optionally enrich results with Claude analysis"},
            {"endpoint": "/scrape/google-maps", "method": "POST", "price_usd": 0.10, "input": {"query": "string (e.g. restaurants in NYC)", "max_items": 5}, "description": "Scrape Google Maps — business names, addresses, ratings, reviews, phone numbers"},
            {"endpoint": "/scrape/tweets", "method": "POST", "price_usd": 0.05, "input": {"query": "string or #hashtag", "max_items": 25}, "description": "Scrape Twitter/X — tweet text, author, engagement metrics"},
            {"endpoint": "/scrape/instagram", "method": "POST", "price_usd": 0.05, "input": {"username": "string", "max_items": 5}, "description": "Scrape Instagram profile posts and metadata"},
            {"endpoint": "/scrape/linkedin", "method": "POST", "price_usd": 0.15, "input": {"url": "LinkedIn profile URL"}, "description": "Scrape LinkedIn profile — experience, skills, education"},
            {"endpoint": "/scrape/youtube", "method": "POST", "price_usd": 0.05, "input": {"query": "string", "max_items": 5}, "description": "Search YouTube and return video metadata — title, channel, views, URL"},
            {"endpoint": "/scrape/web", "method": "POST", "price_usd": 0.05, "input": {"url": "string", "max_pages": 5}, "description": "Crawl any website and extract structured text content"},
            {"endpoint": "/scrape/tiktok", "method": "POST", "price_usd": 0.05, "input": {"username": "string", "max_items": 5}, "description": "Scrape TikTok profile videos and metadata"},
            {"endpoint": "/scrape/facebook-ads", "method": "POST", "price_usd": 0.10, "input": {"url": "Facebook Ad Library URL", "max_items": 10}, "description": "Scrape Facebook Ad Library for competitor ad research"},
            {"endpoint": "/scrape/actor", "method": "POST", "price_usd": 0.10, "input": {"actor_id": "Apify actor ID", "run_input": {}, "max_items": 10}, "description": "Run any Apify actor with custom input — access the full Apify ecosystem"},
            {"endpoint": "/catalog", "method": "GET", "price_usd": 0.00, "input": {"category": "optional", "min_score": 0, "free_only": False, "page": 1}, "description": "Browse 200+ discovered APIs — filtered by category, quality score, auth requirement"},
            {"endpoint": "/run-discovery", "method": "POST", "price_usd": 0.00, "description": "Trigger API discovery agents to scan the web for new APIs"},
            {"endpoint": "/agents/register", "method": "POST", "price_usd": 0.00, "input": {"agent_id": "string", "name": "string", "description": "string", "capabilities": [], "endpoint": "optional URL"}, "description": "Register your agent in the AiPayGent agent registry — free"},
            {"endpoint": "/agents", "method": "GET", "price_usd": 0.00, "description": "Browse all registered agents in the registry"},
            {"endpoint": "/preview", "method": "POST", "price_usd": 0.00, "input": {"topic": "string"}, "description": "Free 120-token Claude preview — no payment required"},
            # ── New: Chain, Marketplace, Free, SDK ────────────────────────────
            {"endpoint": "/chain", "method": "POST", "price_usd": 0.25, "input": {"steps": [{"action": "research", "params": {"query": "string"}}, {"action": "summarize", "params": {"text": "{{prev_result}}"}}]}, "description": "Chain up to 5 AI operations in sequence — each step references previous output via {{prev_result}}"},
            {"endpoint": "/marketplace", "method": "GET", "price_usd": 0.00, "input": {"category": "optional", "max_price": "optional"}, "description": "Browse the agent marketplace — services listed by other AI agents"},
            {"endpoint": "/marketplace/list", "method": "POST", "price_usd": 0.00, "input": {"agent_id": "string", "name": "string", "endpoint": "URL", "price_usd": 0.05, "description": "string", "category": "string"}, "description": "List your service in the agent marketplace — free to list, earn x402 payments"},
            {"endpoint": "/marketplace/call", "method": "POST", "price_usd": 0.05, "input": {"listing_id": "string", "payload": {}}, "description": "Proxy-call any agent marketplace listing — we handle routing ($0.05 + listing price)"},
            {"endpoint": "/free/time", "method": "GET", "price_usd": 0.00, "description": "Current UTC time, Unix timestamp, date, day of week — completely free"},
            {"endpoint": "/free/uuid", "method": "GET", "price_usd": 0.00, "description": "Generate UUID4 values — completely free"},
            {"endpoint": "/free/ip", "method": "GET", "price_usd": 0.00, "description": "Caller's IP address and user agent info — completely free"},
            {"endpoint": "/free/hash", "method": "GET", "price_usd": 0.00, "input": {"text": "string"}, "description": "Hash text with MD5, SHA1, SHA256, SHA512 — completely free"},
            {"endpoint": "/free/base64", "method": "GET", "price_usd": 0.00, "input": {"text": "string to encode", "decode": "string to decode"}, "description": "Encode/decode base64 — completely free"},
            {"endpoint": "/free/random", "method": "GET", "price_usd": 0.00, "input": {"n": 5, "min": 1, "max": 100}, "description": "Random integers, floats, booleans, and strings — completely free"},
            {"endpoint": "/sdk/code", "method": "GET", "price_usd": 0.00, "input": {"lang": "python|javascript|curl", "endpoint": "optional"}, "description": "Get copy-paste SDK code in Python, JavaScript, or cURL — completely free"},
            {"endpoint": "/sitemap.xml", "method": "GET", "price_usd": 0.00, "description": "XML sitemap of all public endpoints for crawlers and agents"},
            # ── Free Data Honeypots ──────────────────────────────────────────────
            {"endpoint": "/data/weather", "method": "GET", "price_usd": 0.00, "input": {"city": "string"}, "description": "Real-time weather — temperature, wind speed, weather code. Free."},
            {"endpoint": "/data/crypto", "method": "GET", "price_usd": 0.00, "input": {"symbol": "bitcoin,ethereum"}, "description": "Live crypto prices in USD/EUR/GBP with 24hr change. Free."},
            {"endpoint": "/data/exchange-rates", "method": "GET", "price_usd": 0.00, "input": {"base": "USD"}, "description": "Exchange rates for any base currency vs 160+ currencies. Free."},
            {"endpoint": "/data/country", "method": "GET", "price_usd": 0.00, "input": {"name": "France"}, "description": "Country info — capital, population, currencies, languages, flag. Free."},
            {"endpoint": "/data/ip", "method": "GET", "price_usd": 0.00, "input": {"ip": "optional"}, "description": "IP geolocation — country, city, ISP, timezone. Free."},
            {"endpoint": "/data/news", "method": "GET", "price_usd": 0.00, "description": "Top 10 Hacker News stories — title, URL, score, comments. Free."},
            {"endpoint": "/data/stocks", "method": "GET", "price_usd": 0.00, "input": {"symbol": "AAPL"}, "description": "Stock price, previous close, market state via Yahoo Finance. Free."},
            {"endpoint": "/data/joke", "method": "GET", "price_usd": 0.00, "description": "Random joke — setup + punchline. Free."},
            {"endpoint": "/data/quote", "method": "GET", "price_usd": 0.00, "input": {"category": "optional"}, "description": "Random inspirational quote with author. Free."},
            {"endpoint": "/data/timezone", "method": "GET", "price_usd": 0.00, "input": {"tz": "America/New_York"}, "description": "Current datetime, UTC offset, week number for any timezone. Free."},
            {"endpoint": "/data/holidays", "method": "GET", "price_usd": 0.00, "input": {"country": "US", "year": "2026"}, "description": "Public holidays for any country and year. Free."},
            # ── Prepaid API Keys ──────────────────────────────────────────────────
            {"endpoint": "/auth/generate-key", "method": "POST", "price_usd": 0.00, "input": {"label": "optional"}, "description": "Generate a prepaid API key (apk_xxx). Use as Bearer token to bypass x402 per-call. Free to generate."},
            {"endpoint": "/auth/topup", "method": "POST", "price_usd": 0.00, "input": {"key": "apk_xxx", "amount": 1.00}, "description": "Top up balance on a prepaid API key. Free to call."},
            {"endpoint": "/auth/status", "method": "GET", "price_usd": 0.00, "input": {"key": "apk_xxx"}, "description": "Check balance, usage stats, and last used time for an API key. Free."},
            # ── SSE Streaming ──────────────────────────────────────────────────────
            {"endpoint": "/stream/research", "method": "POST", "price_usd": 0.01, "input": {"topic": "string"}, "description": "Streaming research — same as /research but tokens stream as text/event-stream SSE"},
            {"endpoint": "/stream/write", "method": "POST", "price_usd": 0.05, "input": {"spec": "string", "type": "article"}, "description": "Streaming write — same as /write but content streams as SSE"},
            {"endpoint": "/stream/analyze", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "question": "optional"}, "description": "Streaming analysis — same as /analyze but streams as SSE"},
            # ── Agent Messaging ───────────────────────────────────────────────────
            {"endpoint": "/message/send", "method": "POST", "price_usd": 0.01, "input": {"from_agent": "string", "to_agent": "string", "subject": "string", "body": "string"}, "description": "Send a message from one agent to another. Persistent inbox."},
            {"endpoint": "/message/inbox/<agent_id>", "method": "GET", "price_usd": 0.00, "description": "Read an agent's inbox. Free."},
            {"endpoint": "/message/reply", "method": "POST", "price_usd": 0.01, "input": {"msg_id": "string", "from_agent": "string", "body": "string"}, "description": "Reply to a message in a thread."},
            {"endpoint": "/message/broadcast", "method": "POST", "price_usd": 0.02, "input": {"from_agent": "string", "subject": "string", "body": "string"}, "description": "Broadcast a message to all registered agents."},
            # ── Shared Knowledge Base ─────────────────────────────────────────────
            {"endpoint": "/knowledge/add", "method": "POST", "price_usd": 0.01, "input": {"topic": "string", "content": "string", "author_agent": "string", "tags": []}, "description": "Add an entry to the shared knowledge base."},
            {"endpoint": "/knowledge/search", "method": "GET", "price_usd": 0.00, "input": {"q": "query"}, "description": "Search the shared knowledge base. Free."},
            {"endpoint": "/knowledge/trending", "method": "GET", "price_usd": 0.00, "description": "Get trending topics in the knowledge base. Free."},
            {"endpoint": "/knowledge/vote", "method": "POST", "price_usd": 0.00, "input": {"entry_id": "string", "up": True}, "description": "Upvote or downvote a knowledge entry. Free."},
            # ── Task Broker ───────────────────────────────────────────────────────
            {"endpoint": "/task/submit", "method": "POST", "price_usd": 0.01, "input": {"posted_by": "string", "title": "string", "description": "string", "skills_needed": [], "reward_usd": 0.10}, "description": "Post a task to the agent task board."},
            {"endpoint": "/task/browse", "method": "GET", "price_usd": 0.00, "input": {"skill": "optional", "status": "open"}, "description": "Browse open tasks. Free."},
            {"endpoint": "/task/claim", "method": "POST", "price_usd": 0.00, "input": {"task_id": "string", "agent_id": "string"}, "description": "Claim a task from the board. Free."},
            {"endpoint": "/task/complete", "method": "POST", "price_usd": 0.01, "input": {"task_id": "string", "agent_id": "string", "result": "string"}, "description": "Mark a task complete with result."},
            # ── Code Execution + Web Search ───────────────────────────────────────
            {"endpoint": "/code/run", "method": "POST", "price_usd": 0.05, "input": {"code": "python code string", "timeout": 10}, "description": "Execute Python code in a sandboxed subprocess. Returns stdout, stderr, exit code."},
            {"endpoint": "/web/search", "method": "GET", "price_usd": 0.02, "input": {"q": "query", "n": 10}, "description": "Web search via DuckDuckGo instant answers — returns results with title, URL, snippet."},
            {"endpoint": "/enrich", "method": "POST", "price_usd": 0.05, "input": {"entity": "string", "type": "ip|crypto|country|url|company"}, "description": "Aggregate multiple data sources into a unified enrichment profile for any entity."},
            # ── Free Daily Tier ───────────────────────────────────────────────────
            {"endpoint": "/free-tier/status", "method": "GET", "price_usd": 0.00, "description": "Check how many free AI calls remain today for your IP. 10 free calls/day, resets midnight UTC."},
            # ── Agent Reputation ──────────────────────────────────────────────────
            {"endpoint": "/agents/leaderboard", "method": "GET", "price_usd": 0.00, "description": "Top agents by reputation score. Score = task_completions×3 + knowledge×1.5 + upvotes×0.5"},
            {"endpoint": "/agent/reputation/<agent_id>", "method": "GET", "price_usd": 0.00, "description": "Get reputation score and stats for any agent."},
            # ── Task Subscriptions ────────────────────────────────────────────────
            {"endpoint": "/task/subscribe", "method": "POST", "price_usd": 0.00, "input": {"agent_id": "string", "callback_url": "https://your-agent/webhook", "skills": ["python", "nlp"]}, "description": "Subscribe to task board notifications. We POST to your callback_url when matching tasks appear."},
            # ── Async Jobs ────────────────────────────────────────────────────────
            {"endpoint": "/async/submit", "method": "POST", "price_usd": 0.00, "input": {"endpoint": "research", "payload": {"topic": "..."}, "callback_url": "optional"}, "description": "Submit an async job. Runs in background, POSTs result to callback_url when done."},
            {"endpoint": "/async/status/<job_id>", "method": "GET", "price_usd": 0.00, "description": "Check status of an async job — pending, running, completed, or failed."},
            # ── File Storage ──────────────────────────────────────────────────────
            {"endpoint": "/files/upload", "method": "POST", "price_usd": 0.00, "input": {"agent_id": "string", "file": "multipart OR base64_data+filename+content_type"}, "description": "Upload a file (max 10MB). Returns file_id and URL. Free."},
            {"endpoint": "/files/<file_id>", "method": "GET", "price_usd": 0.00, "description": "Download a file by ID. Returns raw file bytes."},
            {"endpoint": "/files/list/<agent_id>", "method": "GET", "price_usd": 0.00, "description": "List all files uploaded by an agent."},
            # ── Webhook Relay ─────────────────────────────────────────────────────
            {"endpoint": "/webhooks/create", "method": "POST", "price_usd": 0.00, "input": {"agent_id": "string", "label": "optional"}, "description": "Get a unique URL to receive webhooks from any external service. Events stored 7 days."},
            {"endpoint": "/webhooks/<id>/receive", "method": "POST", "price_usd": 0.00, "description": "The URL external services POST to. Stores the incoming event for your agent to retrieve."},
            {"endpoint": "/webhooks/<id>/events", "method": "GET", "price_usd": 0.00, "description": "Retrieve stored webhook events. Poll this or set up a task subscription callback."},
            # ── Expanded Free Data ────────────────────────────────────────────────
            {"endpoint": "/data/wikipedia", "method": "GET", "price_usd": 0.00, "input": {"q": "quantum computing"}, "description": "Wikipedia article summary — title, extract, URL, description. Free."},
            {"endpoint": "/data/arxiv", "method": "GET", "price_usd": 0.00, "input": {"q": "LLM agents", "limit": 5}, "description": "Search arXiv academic papers — title, authors, summary, URL. Free."},
            {"endpoint": "/data/github/trending", "method": "GET", "price_usd": 0.00, "input": {"lang": "python", "since": "daily"}, "description": "GitHub trending repositories — repo, stars, description, language. Free."},
            {"endpoint": "/data/reddit", "method": "GET", "price_usd": 0.00, "input": {"q": "AI agents", "sub": "MachineLearning"}, "description": "Reddit search — posts with score, comments, URL. Free."},
            {"endpoint": "/data/youtube/transcript", "method": "GET", "price_usd": 0.00, "input": {"video_id": "dQw4w9WgXcQ"}, "description": "YouTube video transcript/captions — full text and segments. Free."},
            {"endpoint": "/data/qr", "method": "GET", "price_usd": 0.00, "input": {"text": "https://api.aipaygent.xyz"}, "description": "Generate QR code — returns PNG as base64 and data URL. Free."},
            {"endpoint": "/data/dns", "method": "GET", "price_usd": 0.00, "input": {"domain": "api.aipaygent.xyz"}, "description": "DNS lookup — A, AAAA records and reverse hostname. Free."},
            {"endpoint": "/data/validate/email", "method": "GET", "price_usd": 0.00, "input": {"email": "test@example.com"}, "description": "Email validation — format check, domain reachability, disposable detection. Free."},
            {"endpoint": "/data/validate/url", "method": "GET", "price_usd": 0.00, "input": {"url": "https://example.com"}, "description": "URL reachability check — status code, final URL, content type. Free."},
            {"endpoint": "/data/random/name", "method": "GET", "price_usd": 0.00, "input": {"count": 5}, "description": "Random person names, emails, phone, location. Free."},
            {"endpoint": "/data/color", "method": "GET", "price_usd": 0.00, "input": {"hex": "ff5733"}, "description": "Color info — RGB, HSL, complementary color, brightness, CSS. Free."},
            {"endpoint": "/data/screenshot", "method": "GET", "price_usd": 0.00, "input": {"url": "https://example.com"}, "description": "Website screenshot URL (1280px wide). Free via thum.io."},
        ]
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "wallet": WALLET_ADDRESS, "network": EVM_NETWORK})


@app.route("/preview", methods=["GET", "POST"])
def preview():
    """Free demo endpoint — no payment required. Returns a short Claude response to prove the service works."""
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", request.args.get("topic", "x402 payment protocol for AI agents"))
    topic = topic[:200]  # cap input length
    ck = f"preview:{_hashlib.md5(topic.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    llm_result, err = _call_llm(
        [{"role": "user", "content": f"In 2-3 sentences, briefly explain: {topic}"}],
        max_tokens=120, endpoint="/preview",
    )
    if err:
        return jsonify({"error": err}), 400
    result = {
        "result": llm_result["text"],
        "model": llm_result["model"],
        "free": True,
        "note": "This preview is capped at 120 tokens. Full /research returns structured summary + key points + sources for $0.01 USDC.",
        "full_api": "https://api.aipaygent.xyz/discover",
        "openapi": "https://api.aipaygent.xyz/openapi.json",
    }
    _cache_set(ck, result, 300)  # 5 min
    return jsonify(result)


@app.route("/robots.txt")
def robots_txt():
    from flask import Response
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "Sitemap: https://api.aipaygent.xyz/sitemap.xml\n"
        "\n"
        "# AI Agent Discovery\n"
        "# LLMs.txt: https://api.aipaygent.xyz/llms.txt\n"
        "# OpenAPI: https://api.aipaygent.xyz/openapi.json\n"
        "# Manifest: https://api.aipaygent.xyz/.well-known/agent.json\n"
        "# Free demo: https://api.aipaygent.xyz/preview\n"
    )
    return Response(body, mimetype="text/plain")


LLMS_TXT = """\
# AiPayGent

> The AI agent API marketplace. 140+ Claude-powered endpoints + web scrapers + file storage + webhook relay + async jobs + real-time data. First 10 calls/day free. No API keys needed. Pay in USDC on Base via x402 or top up via Stripe. Also available as 79+ MCP tools.

## What This Service Does

AiPayGent is an x402-native resource server and MCP tool provider. Call any endpoint, receive HTTP 402 with payment instructions, attach a signed USDC payment, and receive results. Built for autonomous AI agent pipelines.

**Key capabilities:**
- **AI reasoning**: research, write, code, analyze, translate, summarize, classify, sentiment, RAG, workflow
- **Vision**: analyze images via URL using Claude Vision
- **Diagrams**: generate Mermaid diagrams (flowchart, sequence, ERD, gantt, mindmap)
- **Web scraping**: Google Maps, Twitter/X, Instagram, LinkedIn, YouTube, TikTok, Facebook Ads, any website
- **Agent memory**: persistent key-value store keyed by agent_id — survives across sessions
- **API catalog**: 200+ discovered APIs, browsable and proxy-callable
- **Agent registry**: register and discover other agents
- **MCP tools**: all capabilities available as MCP tools at mcp.aipaygent.xyz/mcp

## Payment Protocol

- **Standard**: [x402](https://x402.org) — HTTP 402 Payment Required
- **Network**: Base Mainnet (eip155:8453)
- **Token**: USDC (6 decimals — $0.01 = 10000 units)
- **No auth, no API keys, no rate limits, no accounts**

Flow: POST endpoint → 402 with `X-Payment-Info` → retry with `X-Payment: <signed-tx>` header.

## MCP Integration (Free, No Payment Needed)

```bash
# Claude Code
claude mcp add aipaygent -- python /path/to/mcp_server.py

# Or use the PyPI package
pip install aipaygent-mcp
mcp install aipaygent-mcp
```

MCP SSE endpoint: https://mcp.aipaygent.xyz/mcp
All 79+ tools available without x402 payment via MCP.

## Core AI Endpoints

| Endpoint | Price | Input | Output |
|---|---|---|---|
| /research | $0.01 | `{"topic": "string"}` | summary, key_points, sources_to_check |
| /summarize | $0.01 | `{"text": "string", "length": "short\|medium\|detailed"}` | compressed text |
| /analyze | $0.02 | `{"content": "string", "question": "string"}` | conclusion, findings, sentiment, confidence |
| /translate | $0.02 | `{"text": "string", "language": "string"}` | translated text |
| /social | $0.03 | `{"topic": "string", "platforms": ["twitter","linkedin"], "tone": "string"}` | per-platform posts |
| /write | $0.05 | `{"spec": "string", "type": "article\|post\|copy"}` | written content |
| /code | $0.05 | `{"description": "string", "language": "string"}` | code string |
| /extract | $0.02 | `{"text": "string", "fields": ["name","date"]}` | structured JSON |
| /qa | $0.02 | `{"context": "string", "question": "string"}` | answer, confidence, citation |
| /rag | $0.05 | `{"documents": "text (--- separated)", "query": "string"}` | answer, citations, cannot_answer |
| /classify | $0.01 | `{"text": "string", "categories": ["cat1","cat2"]}` | category, confidence, scores |
| /sentiment | $0.01 | `{"text": "string"}` | polarity, score, emotions, confidence |
| /keywords | $0.01 | `{"text": "string", "max_keywords": 10}` | keywords, topics, entities |
| /compare | $0.02 | `{"text_a": "string", "text_b": "string"}` | similarities, differences, recommendation |
| /transform | $0.02 | `{"text": "string", "instruction": "string"}` | transformed text |
| /chat | $0.03 | `{"messages": [{"role": "user", "content": "hi"}], "system": "optional"}` | reply |
| /plan | $0.03 | `{"goal": "string", "context": "optional", "steps": 7}` | steps, timeline, risks |
| /decide | $0.03 | `{"decision": "string", "options": ["A","B"]}` | pros/cons, recommendation |
| /proofread | $0.02 | `{"text": "string"}` | corrected, changes, score |
| /explain | $0.02 | `{"concept": "string", "level": "beginner\|intermediate\|expert"}` | explanation, analogy |
| /email | $0.03 | `{"purpose": "string", "tone": "professional"}` | subject, body, cta |
| /sql | $0.05 | `{"description": "string", "dialect": "postgresql"}` | query, explanation |
| /regex | $0.02 | `{"description": "string", "language": "python"}` | pattern, flags, examples |
| /mock | $0.03 | `{"description": "string", "count": 5, "format": "json\|csv\|list"}` | mock records |
| /score | $0.02 | `{"content": "string", "criteria": ["clarity","accuracy"]}` | per-criterion scores |
| /timeline | $0.02 | `{"text": "string"}` | chronological events |
| /action | $0.01 | `{"text": "string"}` | action items, owners, due dates |
| /pitch | $0.03 | `{"product": "string", "audience": "string"}` | hook, value_prop, cta, script |
| /debate | $0.03 | `{"topic": "string"}` | for/against arguments with strength ratings |
| /headline | $0.01 | `{"content": "string", "count": 5}` | headline variations |
| /fact | $0.02 | `{"text": "string"}` | factual claims with verifiability scores |
| /rewrite | $0.02 | `{"text": "string", "audience": "string"}` | rewritten text |
| /tag | $0.01 | `{"text": "string", "taxonomy": ["optional"]}` | tags, primary_tag |
| /diagram | $0.03 | `{"description": "string", "type": "flowchart\|sequence\|erd\|gantt\|mindmap"}` | mermaid code |
| /json-schema | $0.02 | `{"description": "string", "example": "optional"}` | JSON Schema draft-07 |
| /test-cases | $0.03 | `{"code": "string", "language": "python"}` | test_cases array |
| /workflow | $0.20 | `{"goal": "string", "data": "optional context"}` | multi-step Claude Sonnet reasoning |
| /vision | $0.05 | `{"url": "image_url", "question": "optional"}` | image analysis text |
| /batch | $0.10 | `{"operations": [{"endpoint": "research", "input": {}}]}` | up to 5 ops, one payment |
| /pipeline | $0.15 | `{"steps": [{"endpoint": "string", "input": {}}]}` | chained ops, {{prev}} references |

## Web Scraping Endpoints (via Apify)

| Endpoint | Price | Input | Returns |
|---|---|---|---|
| /scrape/google-maps | $0.10 | `{"query": "restaurants in NYC", "max_items": 5}` | names, addresses, ratings, phones |
| /scrape/tweets | $0.05 | `{"query": "#AI", "max_items": 25}` | tweets, authors, engagement |
| /scrape/instagram | $0.05 | `{"username": "string", "max_items": 5}` | posts, captions, likes |
| /scrape/linkedin | $0.15 | `{"url": "profile URL"}` | experience, skills, education |
| /scrape/youtube | $0.05 | `{"query": "string", "max_items": 5}` | titles, channels, views, URLs |
| /scrape/web | $0.05 | `{"url": "string", "max_pages": 5}` | crawled page text |
| /scrape/tiktok | $0.05 | `{"username": "string", "max_items": 5}` | videos, captions, stats |
| /scrape/facebook-ads | $0.10 | `{"url": "Ad Library URL", "max_items": 10}` | ad creative, spend, audience |
| /scrape/actor | $0.10 | `{"actor_id": "string", "run_input": {}}` | any Apify actor results |

## Agent Memory Endpoints (persistent across sessions)

| Endpoint | Price | Input | Returns |
|---|---|---|---|
| /memory/set | $0.01 | `{"agent_id": "string", "key": "string", "value": "any", "tags": []}` | stored: true |
| /memory/get | $0.01 | `{"agent_id": "string", "key": "string"}` | value, tags, timestamps |
| /memory/search | $0.02 | `{"agent_id": "string", "query": "string"}` | matching key-value pairs |
| /memory/clear | $0.01 | `{"agent_id": "string"}` | deleted count |

## Free Endpoints (no payment needed)

- `GET /discover` — full machine-readable service manifest (JSON)
- `GET /openapi.json` — OpenAPI 3.1 spec
- `GET /catalog` — browse 200+ discovered APIs (filterable)
- `GET /agents` — browse registered agents
- `POST /agents/register` — register your agent
- `POST /run-discovery` — trigger API discovery agents
- `GET /health` — service health check
- `POST /preview` — free 120-token Claude demo
- `GET /.well-known/agents.json` — Wild Card AI agents.json standard
- `GET /.well-known/ai-plugin.json` — OpenAI plugin manifest
- `GET /llms.txt` — this file

## Quick Start

```python
# MCP (no payment needed)
import subprocess
subprocess.run(["mcp", "install", "aipaygent-mcp"])

# x402 HTTP (pay per use)
import httpx
BASE = "https://api.aipaygent.xyz"

# Free preview
print(httpx.post(f"{BASE}/preview", json={"topic": "AI agents"}).json())

# Discover all services
manifest = httpx.get(f"{BASE}/discover").json()
print(f"{len(manifest['services'])} services available")

# With x402 payment (use coinbase/x402 client)
# r = httpx.post(f"{BASE}/research", json={"topic": "quantum computing"},
#                headers={"X-Payment": signed_payment_header})
```

## Notes for AI Agents

- All paid responses include `_meta` with endpoint, model, network, timestamp.
- Fetch `/discover` to get the machine-readable manifest before calling endpoints.
- USDC precision: $0.01 = 10000 (6 decimals). Network: Base Mainnet (eip155:8453).
- Agent memory persists indefinitely — use a stable `agent_id` (e.g. your agent's DID or UUID).
- `/workflow` uses Claude Sonnet (more capable) for complex multi-step reasoning.
- The `/catalog` endpoint lists 500+ APIs discovered by our 6 autonomous discovery agents.
"""


@app.route("/openapi.json")
def openapi_spec():
    base_url = "https://api.aipaygent.xyz"
    return jsonify({
        "openapi": "3.1.0",
        "info": {
            "title": "AiPayGent",
            "description": (
                "Pay-per-use Claude AI API for autonomous agents. "
                "No API keys. Pay in USDC on Base Mainnet via x402 protocol. "
                "POST to any endpoint — receive HTTP 402 with payment instructions — "
                "retry with signed USDC payment header — get your result."
            ),
            "version": "1.0.0",
            "x-payment-protocol": "x402",
            "x-payment-network": EVM_NETWORK,
            "x-payment-token": "USDC",
        },
        "servers": [{"url": base_url}],
        "paths": {
            "/research": {
                "post": {
                    "operationId": "research",
                    "summary": "Research a topic",
                    "description": "Claude researches a topic and returns a structured summary, key points, and sources to check. Costs $0.01 USDC per call via x402.",
                    "x-price-usd": 0.01,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["topic"],
                            "properties": {"topic": {"type": "string", "description": "The topic to research"}}
                        }}}
                    },
                    "responses": {"200": {"description": "Research result", "content": {"application/json": {"schema": {"type": "object", "properties": {"result": {"type": "string"}, "topic": {"type": "string"}}}}}}, "402": {"description": "Payment required"}}
                }
            },
            "/summarize": {
                "post": {
                    "operationId": "summarize",
                    "summary": "Summarize long text",
                    "description": "Compress long text into key points. Costs $0.01 USDC per call via x402.",
                    "x-price-usd": 0.01,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string", "description": "Text to summarize"},
                                "length": {"type": "string", "enum": ["short", "medium", "detailed"], "default": "short"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Summary result"}, "402": {"description": "Payment required"}}
                }
            },
            "/analyze": {
                "post": {
                    "operationId": "analyze",
                    "summary": "Analyze content",
                    "description": "Deep structured analysis of any content or data. Costs $0.02 USDC per call via x402.",
                    "x-price-usd": 0.02,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["content"],
                            "properties": {
                                "content": {"type": "string", "description": "Content to analyze"},
                                "question": {"type": "string", "description": "What to analyze for", "default": "Provide a structured analysis"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Analysis result"}, "402": {"description": "Payment required"}}
                }
            },
            "/translate": {
                "post": {
                    "operationId": "translate",
                    "summary": "Translate text",
                    "description": "Translate text to any language. Costs $0.02 USDC per call via x402.",
                    "x-price-usd": 0.02,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string", "description": "Text to translate"},
                                "language": {"type": "string", "description": "Target language", "default": "Spanish"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Translation result"}, "402": {"description": "Payment required"}}
                }
            },
            "/social": {
                "post": {
                    "operationId": "social",
                    "summary": "Generate social media posts",
                    "description": "Generate platform-optimized posts for Twitter, LinkedIn, Instagram and more. Costs $0.03 USDC per call via x402.",
                    "x-price-usd": 0.03,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["topic"],
                            "properties": {
                                "topic": {"type": "string", "description": "Topic or content for the posts"},
                                "platforms": {"type": "array", "items": {"type": "string"}, "default": ["twitter", "linkedin", "instagram"]},
                                "tone": {"type": "string", "default": "engaging"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Social posts result"}, "402": {"description": "Payment required"}}
                }
            },
            "/write": {
                "post": {
                    "operationId": "write",
                    "summary": "Write content",
                    "description": "Write articles, copy, or content to your specification. Costs $0.05 USDC per call via x402.",
                    "x-price-usd": 0.05,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["spec"],
                            "properties": {
                                "spec": {"type": "string", "description": "Content specification"},
                                "type": {"type": "string", "enum": ["article", "post", "copy"], "default": "article"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Written content result"}, "402": {"description": "Payment required"}}
                }
            },
            "/code": {
                "post": {
                    "operationId": "code",
                    "summary": "Generate code",
                    "description": "Generate production-ready code in any language from a description. Costs $0.05 USDC per call via x402.",
                    "x-price-usd": 0.05,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["description"],
                            "properties": {
                                "description": {"type": "string", "description": "What to build"},
                                "language": {"type": "string", "description": "Programming language", "default": "Python"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Generated code result"}, "402": {"description": "Payment required"}}
                }
            },
            "/batch": {
                "post": {
                    "operationId": "batch",
                    "summary": "Run multiple operations in one payment",
                    "description": "Execute up to 5 operations in a single x402 payment. Best value for agents running multi-step pipelines. Costs $0.10 USDC per call.",
                    "x-price-usd": 0.10,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["operations"],
                            "properties": {
                                "operations": {
                                    "type": "array",
                                    "maxItems": 5,
                                    "items": {
                                        "type": "object",
                                        "required": ["endpoint", "input"],
                                        "properties": {
                                            "endpoint": {"type": "string", "description": "Endpoint name, e.g. /research"},
                                            "input": {"type": "object", "description": "Input payload for that endpoint"}
                                        }
                                    }
                                }
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Array of results"}, "402": {"description": "Payment required"}}
                }
            },
            "/preview": {
                "post": {
                    "operationId": "preview",
                    "summary": "Free 120-token preview",
                    "description": "Try the service before paying. Returns a capped 120-token research preview. Free, no payment required.",
                    "x-price-usd": 0.00,
                    "requestBody": {
                        "required": False,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {"topic": {"type": "string", "description": "Topic to preview"}}
                        }}}
                    },
                    "responses": {"200": {"description": "Preview result with link to full API"}}
                }
            },
            "/score": {
                "post": {
                    "operationId": "score",
                    "summary": "Score content quality",
                    "description": "Score content on any custom rubric. Returns per-criterion scores, strengths, weaknesses, and recommendation. Costs $0.02 USDC via x402.",
                    "x-price-usd": 0.02,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["content"],
                            "properties": {
                                "content": {"type": "string", "description": "Content to score"},
                                "criteria": {"type": "array", "items": {"type": "string"}, "default": ["clarity", "accuracy", "engagement"], "description": "Scoring criteria"},
                                "scale": {"type": "integer", "default": 10, "description": "Maximum score value"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Score result with per-criterion breakdown"}, "402": {"description": "Payment required"}}
                }
            },
            "/timeline": {
                "post": {
                    "operationId": "timeline",
                    "summary": "Extract timeline of events",
                    "description": "Extract or reconstruct a chronological timeline from any text. Returns dated events with significance ratings. Costs $0.02 USDC via x402.",
                    "x-price-usd": 0.02,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string", "description": "Source text to extract timeline from"},
                                "direction": {"type": "string", "enum": ["chronological", "reverse"], "default": "chronological"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Timeline with events, span, and summary"}, "402": {"description": "Payment required"}}
                }
            },
            "/action": {
                "post": {
                    "operationId": "action",
                    "summary": "Extract action items",
                    "description": "Extract action items, tasks, owners, and due dates from meeting notes or any text. Costs $0.01 USDC via x402.",
                    "x-price-usd": 0.01,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string", "description": "Meeting notes or text containing tasks"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Action items with owners, due dates, and priorities"}, "402": {"description": "Payment required"}}
                }
            },
            "/pitch": {
                "post": {
                    "operationId": "pitch",
                    "summary": "Generate elevator pitch",
                    "description": "Generate a timed elevator pitch with hook, value prop, and call to action. Costs $0.03 USDC via x402.",
                    "x-price-usd": 0.03,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["product"],
                            "properties": {
                                "product": {"type": "string", "description": "Product, service, or idea to pitch"},
                                "audience": {"type": "string", "description": "Target audience (e.g. investors, customers)", "default": "general"},
                                "length": {"type": "string", "enum": ["15s", "30s", "60s"], "default": "30s"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Pitch with hook, value prop, call to action, and full script"}, "402": {"description": "Payment required"}}
                }
            },
            "/debate": {
                "post": {
                    "operationId": "debate",
                    "summary": "Arguments for and against a position",
                    "description": "Generate structured debate arguments with strength ratings and a verdict. Costs $0.03 USDC via x402.",
                    "x-price-usd": 0.03,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["topic"],
                            "properties": {
                                "topic": {"type": "string", "description": "Topic or position to debate"},
                                "perspective": {"type": "string", "enum": ["balanced", "for", "against"], "default": "balanced"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "For/against arguments with strength ratings, verdict, and nuance"}, "402": {"description": "Payment required"}}
                }
            },
            "/headline": {
                "post": {
                    "operationId": "headline",
                    "summary": "Generate headlines and titles",
                    "description": "Generate multiple headline variations for any content with type labels and a best pick. Costs $0.01 USDC via x402.",
                    "x-price-usd": 0.01,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["content"],
                            "properties": {
                                "content": {"type": "string", "description": "Content to generate headlines for"},
                                "count": {"type": "integer", "default": 5, "description": "Number of headlines to generate"},
                                "style": {"type": "string", "default": "engaging", "description": "Headline style (engaging, clickbait, informative, question, how-to)"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Headlines array with types and best pick"}, "402": {"description": "Payment required"}}
                }
            },
            "/fact": {
                "post": {
                    "operationId": "fact",
                    "summary": "Extract factual claims",
                    "description": "Extract factual claims from text with verifiability scores and source hints. Costs $0.02 USDC via x402.",
                    "x-price-usd": 0.02,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string", "description": "Text to extract facts from"},
                                "count": {"type": "integer", "default": 10, "description": "Maximum number of facts to extract"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Facts with verifiability ratings, source hints, and confidence scores"}, "402": {"description": "Payment required"}}
                }
            },
            "/rewrite": {
                "post": {
                    "operationId": "rewrite",
                    "summary": "Rewrite for a target audience",
                    "description": "Rewrite text for a specific audience, reading level, or brand voice. Costs $0.02 USDC via x402.",
                    "x-price-usd": 0.02,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string", "description": "Text to rewrite"},
                                "audience": {"type": "string", "description": "Target audience (e.g. 5th grader, executive, developer)", "default": "general audience"},
                                "tone": {"type": "string", "description": "Desired tone (e.g. friendly, formal, casual)", "default": "neutral"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Rewritten text"}, "402": {"description": "Payment required"}}
                }
            },
            "/tag": {
                "post": {
                    "operationId": "tag",
                    "summary": "Auto-tag content",
                    "description": "Tag content using a provided taxonomy or free-form tagging. Returns tags, primary tag, and categories. Costs $0.01 USDC via x402.",
                    "x-price-usd": 0.01,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string", "description": "Content to tag"},
                                "taxonomy": {"type": "array", "items": {"type": "string"}, "description": "Optional list of allowed tags. Omit for free-form tagging."},
                                "max_tags": {"type": "integer", "default": 10, "description": "Maximum number of tags to return"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Tags, primary tag, and categories"}, "402": {"description": "Payment required"}}
                }
            },
            "/pipeline": {
                "post": {
                    "operationId": "pipeline",
                    "summary": "Chain operations with output passing",
                    "description": "Chain up to 5 operations where each step can reference the previous step's output using {{prev}}. Costs $0.15 USDC via x402.",
                    "x-price-usd": 0.15,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["steps"],
                            "properties": {
                                "steps": {
                                    "type": "array",
                                    "maxItems": 5,
                                    "description": "Ordered list of steps to execute",
                                    "items": {
                                        "type": "object",
                                        "required": ["endpoint", "input"],
                                        "properties": {
                                            "endpoint": {"type": "string", "description": "Endpoint name, e.g. research"},
                                            "input": {"type": "object", "description": "Input payload. Use \"{{prev}}\" as a value to inject the previous step's output."}
                                        }
                                    }
                                }
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Step-by-step results with final_output"}, "402": {"description": "Payment required"}}
                }
            },
            "/discover": {
                "get": {
                    "operationId": "discover",
                    "summary": "Service manifest",
                    "description": "Machine-readable JSON manifest of all services, prices, and payment details. Free.",
                    "responses": {"200": {"description": "Service manifest"}}
                }
            },
            "/data/weather": {
                "get": {
                    "operationId": "get_weather",
                    "summary": "Live weather data (FREE)",
                    "description": "Current weather for any city via Open-Meteo. Returns temperature, wind speed, weather code. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [{"name": "city", "in": "query", "required": True, "schema": {"type": "string"}, "description": "City name (e.g. London, Tokyo, New York)"}],
                    "responses": {"200": {"description": "Temperature, wind, weather code, lat/lon"}}
                }
            },
            "/data/crypto": {
                "get": {
                    "operationId": "get_crypto",
                    "summary": "Crypto prices (FREE)",
                    "description": "Real-time prices from CoinGecko for bitcoin, ethereum, and 10k+ tokens. Returns USD/EUR/GBP prices and 24h change. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [{"name": "symbol", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Comma-separated coin IDs (e.g. bitcoin,ethereum,solana)"}],
                    "responses": {"200": {"description": "Prices in USD/EUR/GBP with 24h change"}}
                }
            },
            "/data/exchange-rates": {
                "get": {
                    "operationId": "get_exchange_rates",
                    "summary": "Currency exchange rates (FREE)",
                    "description": "Live rates for 160+ currencies. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [{"name": "base", "in": "query", "schema": {"type": "string", "default": "USD"}, "description": "Base currency (e.g. USD, EUR, GBP)"}],
                    "responses": {"200": {"description": "Exchange rates object keyed by currency code"}}
                }
            },
            "/data/ip": {
                "get": {
                    "operationId": "get_ip_geo",
                    "summary": "IP geolocation (FREE)",
                    "description": "Geolocate any IP: city, country, ISP, lat/lon. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [{"name": "ip", "in": "query", "schema": {"type": "string"}, "description": "IP address to look up (omit to use your own)"}],
                    "responses": {"200": {"description": "City, country, ISP, lat/lon, timezone"}}
                }
            },
            "/data/news": {
                "get": {
                    "operationId": "get_news",
                    "summary": "Top Hacker News stories (FREE)",
                    "description": "Top 10 Hacker News stories right now. Free.",
                    "x-price-usd": 0.00,
                    "responses": {"200": {"description": "Array of top stories with title, url, score, comments"}}
                }
            },
            "/data/country": {
                "get": {
                    "operationId": "get_country",
                    "summary": "Country facts (FREE)",
                    "description": "Country details: capital, population, languages, currencies, flags. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [{"name": "name", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Country name (e.g. France, Brazil, Japan)"}],
                    "responses": {"200": {"description": "Capital, population, languages, currencies, flags"}}
                }
            },
            "/data/stocks": {
                "get": {
                    "operationId": "get_stocks",
                    "summary": "Stock price (FREE)",
                    "description": "Real-time stock price from Yahoo Finance. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [{"name": "symbol", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Ticker symbol (e.g. AAPL, TSLA, GOOGL)"}],
                    "responses": {"200": {"description": "Current price, open, high, low, volume"}}
                }
            },
            "/web/search": {
                "get": {
                    "operationId": "web_search",
                    "summary": "Web search via DuckDuckGo",
                    "description": "DuckDuckGo instant answers + related results. Costs $0.02 USDC via x402.",
                    "x-price-usd": 0.02,
                    "parameters": [
                        {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Search query"},
                        {"name": "n", "in": "query", "schema": {"type": "integer", "default": 10}, "description": "Max results (up to 25)"}
                    ],
                    "responses": {"200": {"description": "Instant answer, result array, count"}, "402": {"description": "Payment required"}}
                }
            },
            "/message/send": {
                "post": {
                    "operationId": "send_message",
                    "summary": "Send agent-to-agent message",
                    "description": "Send a message from one agent to another. Messages are stored and can be retrieved via /message/inbox. Costs $0.01 USDC via x402.",
                    "x-price-usd": 0.01,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["from_agent", "to_agent", "body"],
                            "properties": {
                                "from_agent": {"type": "string", "description": "Sender agent ID"},
                                "to_agent": {"type": "string", "description": "Recipient agent ID"},
                                "subject": {"type": "string", "description": "Message subject"},
                                "body": {"type": "string", "description": "Message body"},
                                "thread_id": {"type": "string", "description": "Thread ID for replies (optional)"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "msg_id, thread_id, sent:true"}, "402": {"description": "Payment required"}}
                }
            },
            "/message/inbox/{agent_id}": {
                "get": {
                    "operationId": "get_inbox",
                    "summary": "Read agent inbox (FREE)",
                    "description": "Retrieve messages sent to an agent. Filter by unread. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [
                        {"name": "agent_id", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Agent ID to read inbox for"},
                        {"name": "unread_only", "in": "query", "schema": {"type": "integer", "enum": [0, 1]}, "description": "Set to 1 for unread only"}
                    ],
                    "responses": {"200": {"description": "Array of messages"}}
                }
            },
            "/knowledge/add": {
                "post": {
                    "operationId": "add_knowledge",
                    "summary": "Add to shared knowledge base",
                    "description": "Contribute a knowledge entry to the shared agent knowledge base. Costs $0.01 USDC via x402.",
                    "x-price-usd": 0.01,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["topic", "content", "author_agent"],
                            "properties": {
                                "topic": {"type": "string", "description": "Knowledge topic or category"},
                                "content": {"type": "string", "description": "Knowledge content"},
                                "author_agent": {"type": "string", "description": "Contributing agent ID"},
                                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "entry_id, added:true"}, "402": {"description": "Payment required"}}
                }
            },
            "/knowledge/search": {
                "get": {
                    "operationId": "search_knowledge",
                    "summary": "Search shared knowledge base (FREE)",
                    "description": "Full-text search across all agent-contributed knowledge. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [
                        {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Search query"},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 10}, "description": "Max results"}
                    ],
                    "responses": {"200": {"description": "Matching knowledge entries"}}
                }
            },
            "/task/submit": {
                "post": {
                    "operationId": "submit_task",
                    "summary": "Post a task for other agents",
                    "description": "Post a task on the agent task board. Other agents can claim and complete it. Costs $0.01 USDC via x402.",
                    "x-price-usd": 0.01,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["posted_by", "title", "description"],
                            "properties": {
                                "posted_by": {"type": "string", "description": "Agent ID posting the task"},
                                "title": {"type": "string", "description": "Task title"},
                                "description": {"type": "string", "description": "Detailed task description"},
                                "skills_needed": {"type": "array", "items": {"type": "string"}, "description": "Skills required (e.g. python, web-search)"},
                                "reward_usd": {"type": "number", "default": 0.0, "description": "USDC reward offered"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "task_id, submitted:true"}, "402": {"description": "Payment required"}}
                }
            },
            "/task/browse": {
                "get": {
                    "operationId": "browse_tasks",
                    "summary": "Browse agent task board (FREE)",
                    "description": "Browse open tasks on the agent task board. Filter by skill. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [
                        {"name": "skill", "in": "query", "schema": {"type": "string"}, "description": "Filter by skill (e.g. python, web-search)"},
                        {"name": "status", "in": "query", "schema": {"type": "string", "default": "open"}, "description": "Task status (open, claimed, completed)"}
                    ],
                    "responses": {"200": {"description": "Array of tasks"}}
                }
            },
            "/marketplace": {
                "get": {
                    "operationId": "browse_marketplace",
                    "summary": "Browse agent marketplace (FREE)",
                    "description": "Browse all agent services listed in the marketplace. Filter by category and price. Free.",
                    "x-price-usd": 0.00,
                    "parameters": [
                        {"name": "category", "in": "query", "schema": {"type": "string"}, "description": "Filter by category (data, search, code, scraping, nlp, content, analytics, knowledge)"},
                        {"name": "max_price", "in": "query", "schema": {"type": "number"}, "description": "Maximum price in USD"},
                        {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}}
                    ],
                    "responses": {"200": {"description": "Listings array, total count, pages"}}
                }
            },
            "/marketplace/call": {
                "post": {
                    "operationId": "call_marketplace_service",
                    "summary": "Call any marketplace service",
                    "description": "Proxy call to any marketplace listing. Handles request forwarding + response. Costs $0.05 USDC via x402.",
                    "x-price-usd": 0.05,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["listing_id"],
                            "properties": {
                                "listing_id": {"type": "string", "description": "Marketplace listing ID to call"},
                                "payload": {"type": "object", "description": "Request payload to forward"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Service response"}, "402": {"description": "Payment required"}}
                }
            },
            "/scrape/web": {
                "post": {
                    "operationId": "scrape_web",
                    "summary": "Web crawler (Apify)",
                    "description": "Crawl any website and extract structured content. Costs $0.05 USDC via x402.",
                    "x-price-usd": 0.05,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["url"],
                            "properties": {
                                "url": {"type": "string", "description": "URL to crawl"},
                                "max_pages": {"type": "integer", "default": 5}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Crawled pages with structured content"}, "402": {"description": "Payment required"}}
                }
            },
            "/scrape/google-maps": {
                "post": {
                    "operationId": "scrape_google_maps",
                    "summary": "Google Maps scraper (Apify)",
                    "description": "Scrape places, ratings, addresses, reviews from Google Maps. Costs $0.10 USDC via x402.",
                    "x-price-usd": 0.10,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["query"],
                            "properties": {
                                "query": {"type": "string", "description": "Search query (e.g. 'restaurants in NYC')"},
                                "max_items": {"type": "integer", "default": 5}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Places with ratings, addresses, reviews"}, "402": {"description": "Payment required"}}
                }
            },
            "/code/run": {
                "post": {
                    "operationId": "run_code",
                    "summary": "Execute Python code",
                    "description": "Run Python code in a sandboxed subprocess. Returns stdout, stderr, return code. Costs $0.05 USDC via x402.",
                    "x-price-usd": 0.05,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["code"],
                            "properties": {
                                "code": {"type": "string", "description": "Python code to execute (max 5000 chars)"},
                                "timeout": {"type": "integer", "default": 10, "description": "Timeout in seconds (max 15)"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "stdout, stderr, returncode, execution_time_ms"}, "402": {"description": "Payment required"}}
                }
            },
            "/enrich": {
                "post": {
                    "operationId": "enrich_entity",
                    "summary": "Entity enrichment",
                    "description": "Aggregate data from multiple sources for an IP, crypto token, country, or company. Returns a unified enrichment profile. Costs $0.05 USDC via x402.",
                    "x-price-usd": 0.05,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["entity", "type"],
                            "properties": {
                                "entity": {"type": "string", "description": "Entity to enrich (IP address, coin ID, country name, company name)"},
                                "type": {"type": "string", "enum": ["ip", "crypto", "country", "company"], "description": "Entity type"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Enriched profile with data from multiple sources"}, "402": {"description": "Payment required"}}
                }
            },
            "/agents": {
                "get": {
                    "operationId": "list_agents",
                    "summary": "List registered agents (FREE)",
                    "description": "List all agents registered in the agent registry. Free.",
                    "x-price-usd": 0.00,
                    "responses": {"200": {"description": "Array of agents with capabilities and endpoints"}}
                }
            },
            "/agents/register": {
                "post": {
                    "operationId": "register_agent",
                    "summary": "Register an agent (FREE)",
                    "description": "Register your agent in the shared agent registry. Free — we want your agent here.",
                    "x-price-usd": 0.00,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["agent_id", "name", "capabilities"],
                            "properties": {
                                "agent_id": {"type": "string", "description": "Unique agent identifier"},
                                "name": {"type": "string", "description": "Human-readable agent name"},
                                "description": {"type": "string"},
                                "capabilities": {"type": "array", "items": {"type": "string"}, "description": "List of capability tags"},
                                "endpoint": {"type": "string", "description": "Your agent's base URL"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "agent_id, registered:true"}}
                }
            },
            "/rag": {
                "post": {
                    "operationId": "rag_qa",
                    "summary": "RAG document Q&A",
                    "description": "Provide documents + question, get a grounded answer with citations. Costs $0.05 USDC via x402.",
                    "x-price-usd": 0.05,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["query", "documents"],
                            "properties": {
                                "query": {"type": "string", "description": "Question to answer"},
                                "documents": {"type": "array", "items": {"type": "string"}, "description": "Array of document texts to search"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Answer with citations and confidence score"}, "402": {"description": "Payment required"}}
                }
            },
            "/vision": {
                "post": {
                    "operationId": "vision_analysis",
                    "summary": "Image analysis (vision)",
                    "description": "Analyze an image URL with Claude vision. Returns structured description, objects, text, sentiment. Costs $0.05 USDC via x402.",
                    "x-price-usd": 0.05,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["image_url"],
                            "properties": {
                                "image_url": {"type": "string", "description": "Public URL of image to analyze"},
                                "question": {"type": "string", "description": "Specific question about the image"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Description, objects, text, sentiment, answer"}, "402": {"description": "Payment required"}}
                }
            },
            "/workflow": {
                "post": {
                    "operationId": "agentic_workflow",
                    "summary": "Multi-step agentic workflow",
                    "description": "Multi-step agentic reasoning with Claude Sonnet. Breaks goal into steps, executes each, returns structured plan + results. Costs $0.20 USDC via x402.",
                    "x-price-usd": 0.20,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["goal"],
                            "properties": {
                                "goal": {"type": "string", "description": "High-level goal for the agent to accomplish"},
                                "context": {"type": "string", "description": "Additional context"}
                            }
                        }}}
                    },
                    "responses": {"200": {"description": "Plan, steps, results, summary"}, "402": {"description": "Payment required"}}
                }
            },
        }
    })


@app.route("/llms.txt")
def llms_txt():
    from flask import Response
    return Response(LLMS_TXT, content_type="text/plain; charset=utf-8")


@app.route("/.well-known/ai-plugin.json")
def ai_plugin():
    base_url = "https://api.aipaygent.xyz"
    return jsonify({
        "schema_version": "v1",
        "name_for_human": "AiPayGent",
        "name_for_model": "aipaygent",
        "description_for_human": "Pay-per-use Claude AI services. Research, write, code, translate, analyze — pay in USDC on Base. No API key needed.",
        "description_for_model": (
            "AiPayGent is an x402 resource server offering Claude-powered AI endpoints. "
            "No API key required. POST to any endpoint, receive HTTP 402 with payment instructions, "
            "attach a signed USDC payment on Base Mainnet (eip155:8453), and receive the result. "
            "Endpoints: /research ($0.01), /summarize ($0.01), /analyze ($0.02), /translate ($0.02), "
            "/social ($0.03), /write ($0.05), /code ($0.05), /batch ($0.10 for up to 5 ops), /preview (free). "
            "GET /discover for the full machine-readable manifest. GET /openapi.json for the OpenAPI 3.1 spec."
        ),
        "auth": {"type": "none"},
        "api": {
            "type": "openapi",
            "url": f"{base_url}/openapi.json",
            "is_user_authenticated": False,
        },
        "logo_url": "https://aipaygent.xyz/favicon.ico",
        "contact_email": "",
        "legal_info_url": f"{base_url}/llms.txt",
    })


@app.route("/.well-known/openapi.json")
def well_known_openapi():
    from flask import redirect
    return redirect("/openapi.json", code=301)


@app.route("/.well-known/agent.json")
def agent_manifest():
    """Google A2A Agent Card — https://google.github.io/A2A/specification/"""
    base = "https://api.aipaygent.xyz"
    return jsonify({
        "name": "AiPayGent",
        "description": (
            "The AI agent API marketplace. 140+ endpoints for research, writing, coding, "
            "analysis, web scraping, real-time data, file storage, webhook relay, async jobs, "
            "agent messaging, shared knowledge base, and a task board. "
            "First 10 calls/day free. No API keys needed — pay in USDC on Base via x402, "
            "or top up via Stripe for instant credits."
        ),
        "url": base,
        "version": "3.0.0",
        "documentationUrl": f"{base}/llms.txt",
        "capabilities": {
            "streaming": True,
            "pushNotifications": True,
            "stateTransitionHistory": False,
        },
        "authentication": {
            "schemes": ["x402", "Bearer"],
            "description": (
                "10 free calls/day — no auth needed. "
                "For unlimited: use 'Authorization: Bearer apk_xxx' with a prepaid key. "
                "Buy credits at https://api.aipaygent.xyz/buy-credits"
            ),
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "research", "name": "Research",
                "description": "Research any topic — returns summary, key points, sources",
                "tags": ["research", "ai", "claude", "knowledge"],
                "examples": ["Research quantum computing breakthroughs in 2025"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "write", "name": "Write Content",
                "description": "Write articles, blog posts, copy, or any content to spec",
                "tags": ["writing", "content", "copywriting"],
                "examples": ["Write a 500-word article about renewable energy"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "code", "name": "Generate Code",
                "description": "Generate code in any language from a description",
                "tags": ["code", "programming", "development"],
                "examples": ["Write a Python function to parse CSV files"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "analyze", "name": "Analyze",
                "description": "Analyze data or text, return structured insights",
                "tags": ["analysis", "data", "insights"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "scrape", "name": "Web Scraping",
                "description": "Scrape Google Maps, Twitter, LinkedIn, YouTube, TikTok, Instagram, any website",
                "tags": ["scraping", "data-collection", "web"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "data", "name": "Real-Time Data",
                "description": "Free real-time weather, crypto, stocks, news, Wikipedia, arXiv, GitHub trending, Reddit, YouTube transcripts",
                "tags": ["data", "real-time", "free"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "memory", "name": "Agent Memory",
                "description": "Persistent key-value memory for agents — survives across sessions",
                "tags": ["memory", "persistence", "storage"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "files", "name": "File Storage",
                "description": "Upload and retrieve files up to 10MB. Returns URL.",
                "tags": ["files", "storage", "upload"],
                "inputModes": ["application/json", "multipart/form-data"],
                "outputModes": ["application/json"],
            },
            {
                "id": "webhooks", "name": "Webhook Relay",
                "description": "Get a unique URL to receive webhooks from any external service",
                "tags": ["webhooks", "callbacks", "events"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "async", "name": "Async Jobs",
                "description": "Submit long-running jobs with a callback URL — fire and forget",
                "tags": ["async", "jobs", "background"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "messaging", "name": "Agent Messaging",
                "description": "Send messages between agents with persistent inbox",
                "tags": ["messaging", "communication", "agents"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
            {
                "id": "tasks", "name": "Task Board",
                "description": "Post tasks for other agents to claim and complete",
                "tags": ["tasks", "collaboration", "marketplace"],
                "inputModes": ["application/json"], "outputModes": ["application/json"],
            },
        ],
        "contact": {"email": "hello@aipaygent.xyz"},
        "openapi": f"{base}/openapi.json",
        "pricing": {
            "free_tier": "10 AI calls/day",
            "prepaid": "Buy credits at /buy-credits — from $5",
            "x402": "Pay-per-call in USDC on Base (testnet while mainnet pending)",
        },
    })


@app.route("/.well-known/agents.json")
def agents_json():
    """Wild Card AI / agentsfoundation.org agents.json discovery standard."""
    base = "https://api.aipaygent.xyz"
    ai_endpoints = [
        "research", "summarize", "analyze", "translate", "social", "write",
        "code", "extract", "qa", "classify", "sentiment", "keywords", "compare",
        "transform", "chat", "plan", "decide", "proofread", "explain", "questions",
        "outline", "email", "sql", "regex", "mock", "score", "timeline", "action",
        "pitch", "debate", "headline", "fact", "rewrite", "tag", "batch", "pipeline",
        "vision", "rag", "diagram", "json-schema", "test-cases", "workflow",
    ]
    scrape_endpoints = [
        "scrape/google-maps", "scrape/tweets", "scrape/instagram", "scrape/linkedin",
        "scrape/youtube", "scrape/web", "scrape/tiktok", "scrape/facebook-ads", "scrape/actor",
    ]
    memory_endpoints = ["memory/set", "memory/get", "memory/search", "memory/clear"]
    free_endpoints = ["preview", "discover", "openapi.json", "catalog", "agents", "agents/register",
                      "run-discovery", "api-call", ".well-known/agents.json", "health"]
    return jsonify({
        "$schema": "https://agentsfoundation.org/agents.json/schema/v1",
        "agents": [{
            "name": "AiPayGent",
            "description": (
                "140+ Claude-powered AI tools + web scrapers + agent memory + file storage + webhook relay + async jobs, available as pay-per-use endpoints. "
                "Research, write, code, analyze, vision, RAG, diagrams, test-cases, workflows, "
                "web scraping (Google Maps, Twitter, LinkedIn, TikTok, YouTube), persistent agent memory, "
                "and a searchable catalog of 200+ discovered APIs. "
                "No API key required — pay in USDC on Base via x402 protocol. "
                "Also available as MCP tools: mcp install aipaygent-mcp"
            ),
            "url": base,
            "version": "2.0.0",
            "capabilities": [
                "research", "writing", "code-generation", "translation",
                "analysis", "summarization", "social-media", "data-extraction",
                "question-answering", "sentiment-analysis", "sql-generation",
                "batch-processing", "pipeline-chaining", "image-analysis",
                "rag", "diagram-generation", "test-generation", "workflow-orchestration",
                "web-scraping", "agent-memory", "api-catalog", "agent-registry",
            ],
            "endpoints": (
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "ai"} for ep in ai_endpoints] +
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "scraping"} for ep in scrape_endpoints] +
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "memory"} for ep in memory_endpoints] +
                [{"path": f"/{ep}", "method": "GET", "free": True} for ep in free_endpoints]
            ),
            "authentication": {
                "type": "x402",
                "description": "HTTP 402 payment protocol. No API key required.",
                "payment": {
                    "protocol": "x402",
                    "network": EVM_NETWORK,
                    "token": "USDC",
                    "prices_from": "0.01",
                    "prices_to": "0.20",
                    "currency": "USD",
                },
            },
            "mcp": {
                "remote": "https://mcp.aipaygent.xyz/mcp",
                "package": "aipaygent-mcp",
                "registry": "pypi",
                "install": "mcp install aipaygent-mcp",
            },
            "links": {
                "openapi": f"{base}/openapi.json",
                "discover": f"{base}/discover",
                "sdk": f"{base}/sdk",
                "llms_txt": f"{base}/llms.txt",
                "mcp": "https://mcp.aipaygent.xyz/mcp",
                "catalog": f"{base}/catalog",
                "agents": f"{base}/agents",
            },
            "contact": "https://aipaygent.xyz",
        }]
    })


@app.route("/.well-known/x402.json")
def x402_manifest():
    """x402 Bazaar auto-discovery manifest — indexes this service in the CDP Bazaar and agent directories."""
    base = "https://api.aipaygent.xyz"
    return jsonify({
        "x402Version": 1,
        "network": EVM_NETWORK,
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base Mainnet
        "payTo": WALLET_ADDRESS,
        "facilitator": FACILITATOR_URL,
        "name": "AiPayGent",
        "description": (
            "140+ Claude-powered AI tools, web scrapers, agent memory, file storage, "
            "webhook relay, async jobs, and an API catalog of 200+ discovered APIs. "
            "No API key required — pay per call in USDC on Base via x402 protocol."
        ),
        "url": base,
        "openapi": f"{base}/openapi.json",
        "llms_txt": f"{base}/llms.txt",
        "categories": ["ai", "scraping", "data", "memory", "workflows", "agent-infrastructure"],
        "endpoints": [
            {"path": "/research", "method": "POST", "price": "$0.01", "description": "AI research on any topic"},
            {"path": "/write", "method": "POST", "price": "$0.05", "description": "Long-form content generation"},
            {"path": "/analyze", "method": "POST", "price": "$0.02", "description": "Data/text analysis"},
            {"path": "/code", "method": "POST", "price": "$0.05", "description": "Code generation in any language"},
            {"path": "/summarize", "method": "POST", "price": "$0.01", "description": "Text summarization"},
            {"path": "/translate", "method": "POST", "price": "$0.01", "description": "Translation between languages"},
            {"path": "/vision", "method": "POST", "price": "$0.05", "description": "Image analysis with Claude"},
            {"path": "/rag", "method": "POST", "price": "$0.05", "description": "RAG over provided documents"},
            {"path": "/workflow", "method": "POST", "price": "$0.20", "description": "Multi-step agentic workflow"},
            {"path": "/chain", "method": "POST", "price": "$0.25", "description": "Pipeline up to 5 AI steps"},
            {"path": "/batch", "method": "POST", "price": "$0.10", "description": "Batch multiple AI calls"},
            {"path": "/scrape/web", "method": "POST", "price": "$0.05", "description": "Web page scraping"},
            {"path": "/scrape/tweets", "method": "POST", "price": "$0.05", "description": "Twitter/X scraping"},
            {"path": "/scrape/linkedin", "method": "POST", "price": "$0.15", "description": "LinkedIn scraping"},
            {"path": "/scrape/google-maps", "method": "POST", "price": "$0.10", "description": "Google Maps data"},
            {"path": "/memory/set", "method": "POST", "price": "$0.01", "description": "Store agent memory"},
            {"path": "/memory/get", "method": "POST", "price": "$0.01", "description": "Retrieve agent memory"},
            {"path": "/web/search", "method": "POST", "price": "$0.02", "description": "Web search"},
            {"path": "/code/run", "method": "POST", "price": "$0.05", "description": "Execute Python code"},
        ],
        "contact": "https://aipaygent.xyz",
        "mcp": "https://mcp.aipaygent.xyz/mcp",
    })


@app.route("/sdk")
def sdk():
    """Copy-paste integration code for Python, JS, curl, and MCP."""
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGent SDK & Integration</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #e6edf3; line-height: 1.6; }
  .header { background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%); border-bottom: 1px solid #30363d; padding: 40px 24px; text-align: center; }
  .header h1 { font-size: 2rem; font-weight: 700; color: #58a6ff; margin-bottom: 8px; }
  .header p { color: #8b949e; font-size: 1.1rem; }
  .container { max-width: 900px; margin: 0 auto; padding: 40px 24px; }
  .section { margin-bottom: 48px; }
  .section h2 { font-size: 1.3rem; font-weight: 600; color: #f0f6fc; margin-bottom: 16px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }
  .tabs { display: flex; gap: 4px; margin-bottom: 0; }
  .tab { padding: 8px 16px; border: 1px solid #30363d; border-bottom: none; border-radius: 6px 6px 0 0; cursor: pointer; font-size: 0.875rem; color: #8b949e; background: #161b22; }
  .tab.active { background: #1a1f2e; color: #58a6ff; border-color: #388bfd; }
  pre { background: #161b22; border: 1px solid #30363d; border-radius: 0 6px 6px 6px; padding: 20px; overflow-x: auto; font-size: 0.85rem; line-height: 1.7; }
  code { font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace; }
  .comment { color: #8b949e; }
  .kw { color: #ff7b72; }
  .str { color: #a5d6ff; }
  .fn { color: #d2a8ff; }
  .num { color: #f2cc60; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; margin-left: 8px; vertical-align: middle; }
  .free-badge { background: #1a4a1a; color: #3fb950; border: 1px solid #238636; }
  .paid-badge { background: #3d1f00; color: #ffa657; border: 1px solid #f0883e; }
  .note { background: #161b22; border: 1px solid #388bfd; border-left: 4px solid #388bfd; border-radius: 0 6px 6px 0; padding: 12px 16px; margin-bottom: 16px; font-size: 0.9rem; color: #79c0ff; }
  .endpoints-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; margin-top: 16px; }
  .endpoint-pill { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 8px 12px; font-size: 0.8rem; }
  .endpoint-pill code { color: #79c0ff; }
  .endpoint-pill .price { color: #f2cc60; float: right; }
  a { color: #58a6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .link-row { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 24px; font-size: 0.9rem; }
</style>
</head>
<body>
<div class="header">
  <h1>AiPayGent SDK</h1>
  <p>Copy-paste integration code for Python, JavaScript, curl, and MCP</p>
</div>
<div class="container">

  <div class="section">
    <div class="note">
      No API keys, no accounts. POST to any endpoint &rarr; receive HTTP 402 with payment instructions &rarr; retry with signed USDC payment header. Use <a href="/preview">/preview</a> to test free.
    </div>
  </div>

  <div class="section">
    <h2>curl <span class="badge free-badge">FREE — test first</span></h2>
    <pre><code><span class="comment"># Free preview — no payment needed</span>
curl https://api.aipaygent.xyz/preview?topic=bitcoin

<span class="comment"># Paid endpoint — will return 402 first</span>
curl -X POST https://api.aipaygent.xyz/research \\
  -H "Content-Type: application/json" \\
  -d \'{"topic": "quantum computing breakthroughs 2025"}\'

<span class="comment"># With x402 payment header (Base Mainnet USDC)</span>
curl -X POST https://api.aipaygent.xyz/research \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: &lt;signed-x402-tx&gt;" \\
  -d \'{"topic": "quantum computing breakthroughs 2025"}\'</code></pre>
  </div>

  <div class="section">
    <h2>Python <span class="badge paid-badge">x402-python</span></h2>
    <pre><code><span class="kw">pip install</span> x402-python anthropic

<span class="comment"># --- research.py ---</span>
<span class="kw">from</span> x402.client <span class="kw">import</span> <span class="fn">X402Client</span>
<span class="kw">from</span> eth_account <span class="kw">import</span> Account
<span class="kw">import</span> json

<span class="comment"># Your EVM wallet (Base Mainnet)</span>
account = Account.<span class="fn">from_key</span>(<span class="str">"YOUR_PRIVATE_KEY"</span>)
client = <span class="fn">X402Client</span>(account)

<span class="comment"># One call handles the 402 handshake automatically</span>
response = client.<span class="fn">post</span>(
    <span class="str">"https://api.aipaygent.xyz/research"</span>,
    json={<span class="str">"topic"</span>: <span class="str">"quantum computing breakthroughs 2025"</span>}
)
data = response.<span class="fn">json</span>()
<span class="fn">print</span>(data[<span class="str">"summary"</span>])
<span class="fn">print</span>(data[<span class="str">"key_points"</span>])

<span class="comment"># --- batch.py (5 tasks, one payment at $0.10) ---</span>
result = client.<span class="fn">post</span>(
    <span class="str">"https://api.aipaygent.xyz/batch"</span>,
    json={<span class="str">"operations"</span>: [
        {<span class="str">"endpoint"</span>: <span class="str">"research"</span>,  <span class="str">"input"</span>: {<span class="str">"topic"</span>: <span class="str">"AI agents 2025"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"summarize"</span>, <span class="str">"input"</span>: {<span class="str">"text"</span>: <span class="str">"..."</span>, <span class="str">"length"</span>: <span class="str">"short"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"sentiment"</span>, <span class="str">"input"</span>: {<span class="str">"text"</span>: <span class="str">"..."</span>}},
    ]}
).<span class="fn">json</span>()

<span class="comment"># --- pipeline.py (chain steps, pass output with {{prev}}) ---</span>
result = client.<span class="fn">post</span>(
    <span class="str">"https://api.aipaygent.xyz/pipeline"</span>,
    json={<span class="str">"steps"</span>: [
        {<span class="str">"endpoint"</span>: <span class="str">"research"</span>,  <span class="str">"input"</span>: {<span class="str">"topic"</span>: <span class="str">"AI regulation EU 2025"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"summarize"</span>, <span class="str">"input"</span>: {<span class="str">"text"</span>: <span class="str">"{{prev}}"</span>, <span class="str">"length"</span>: <span class="str">"short"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"social"</span>,    <span class="str">"input"</span>: {<span class="str">"topic"</span>: <span class="str">"{{prev}}"</span>, <span class="str">"platforms"</span>: [<span class="str">"twitter"</span>]}},
    ]}
).<span class="fn">json</span>()</code></pre>
  </div>

  <div class="section">
    <h2>JavaScript / Node.js <span class="badge paid-badge">x402-fetch</span></h2>
    <pre><code><span class="kw">npm install</span> x402-fetch viem

<span class="comment">// research.mjs</span>
<span class="kw">import</span> { wrapFetchWithPayment } <span class="kw">from</span> <span class="str">"x402-fetch"</span>;
<span class="kw">import</span> { privateKeyToAccount } <span class="kw">from</span> <span class="str">"viem/accounts"</span>;
<span class="kw">import</span> { baseSepolia } <span class="kw">from</span> <span class="str">"viem/chains"</span>;

<span class="kw">const</span> account = <span class="fn">privateKeyToAccount</span>(<span class="str">"0xYOUR_PRIVATE_KEY"</span>);
<span class="kw">const</span> fetchWithPayment = <span class="fn">wrapFetchWithPayment</span>(fetch, account, baseSepolia);

<span class="kw">const</span> res = <span class="kw">await</span> <span class="fn">fetchWithPayment</span>(<span class="str">"https://api.aipaygent.xyz/research"</span>, {
  method: <span class="str">"POST"</span>,
  headers: { <span class="str">"Content-Type"</span>: <span class="str">"application/json"</span> },
  body: <span class="fn">JSON.stringify</span>({ topic: <span class="str">"quantum computing 2025"</span> }),
});
<span class="kw">const</span> data = <span class="kw">await</span> res.<span class="fn">json</span>();
console.<span class="fn">log</span>(data.summary);

<span class="comment">// Generate social posts + translate in one pipeline call</span>
<span class="kw">const</span> pipeline = <span class="kw">await</span> <span class="fn">fetchWithPayment</span>(<span class="str">"https://api.aipaygent.xyz/pipeline"</span>, {
  method: <span class="str">"POST"</span>,
  headers: { <span class="str">"Content-Type"</span>: <span class="str">"application/json"</span> },
  body: <span class="fn">JSON.stringify</span>({ steps: [
    { endpoint: <span class="str">"write"</span>,      input: { spec: <span class="str">"blog post about x402"</span>, type: <span class="str">"article"</span> } },
    { endpoint: <span class="str">"headline"</span>,   input: { content: <span class="str">"{{prev}}"</span>, count: <span class="num">5</span> } },
    { endpoint: <span class="str">"translate"</span>,  input: { text: <span class="str">"{{prev}}"</span>, language: <span class="str">"Spanish"</span> } },
  ]}),
});
<span class="kw">const</span> result = <span class="kw">await</span> pipeline.<span class="fn">json</span>();</code></pre>
  </div>

  <div class="section">
    <h2>MCP (Claude Desktop / Cursor / any MCP client)</h2>
    <pre><code><span class="comment"># Option 1 — Remote (no install, no API key needed by client)</span>
<span class="comment"># Add to your MCP client config:</span>
{
  <span class="str">"mcpServers"</span>: {
    <span class="str">"aipaygent"</span>: {
      <span class="str">"type"</span>: <span class="str">"streamable-http"</span>,
      <span class="str">"url"</span>: <span class="str">"https://mcp.aipaygent.xyz/mcp"</span>
    }
  }
}

<span class="comment"># Option 2 — Local via stdio (requires your own ANTHROPIC_API_KEY)</span>
pip install aipaygent-mcp

{
  <span class="str">"mcpServers"</span>: {
    <span class="str">"aipaygent"</span>: {
      <span class="str">"command"</span>: <span class="str">"aipaygent-mcp"</span>,
      <span class="str">"env"</span>: { <span class="str">"ANTHROPIC_API_KEY"</span>: <span class="str">"sk-ant-..."</span> }
    }
  }
}</code></pre>
  </div>

  <div class="section">
    <h2>Claude Agent (Anthropic SDK) <span class="badge paid-badge">Tool use</span></h2>
    <pre><code><span class="kw">pip install</span> anthropic x402-python

<span class="comment"># Give Claude the ability to call AiPayGent tools</span>
<span class="kw">import</span> anthropic, requests
<span class="kw">from</span> x402.client <span class="kw">import</span> X402Client
<span class="kw">from</span> eth_account <span class="kw">import</span> Account

x402 = X402Client(Account.<span class="fn">from_key</span>(<span class="str">"YOUR_PRIVATE_KEY"</span>))

<span class="kw">def</span> <span class="fn">call_aipaygent</span>(endpoint: str, payload: dict) -> dict:
    <span class="kw">return</span> x402.<span class="fn">post</span>(<span class="str">f"https://api.aipaygent.xyz/{endpoint}"</span>, json=payload).<span class="fn">json</span>()

client = anthropic.<span class="fn">Anthropic</span>()
tools = [{
    <span class="str">"name"</span>: <span class="str">"research"</span>,
    <span class="str">"description"</span>: <span class="str">"Research any topic. Returns summary, key points, and sources."</span>,
    <span class="str">"input_schema"</span>: {<span class="str">"type"</span>: <span class="str">"object"</span>, <span class="str">"properties"</span>: {<span class="str">"topic"</span>: {<span class="str">"type"</span>: <span class="str">"string"</span>}}, <span class="str">"required"</span>: [<span class="str">"topic"</span>]},
}]

<span class="comment"># Claude will autonomously call /research and use the result</span>
response = client.messages.<span class="fn">create</span>(
    model=<span class="str">"claude-sonnet-4-6"</span>, max_tokens=<span class="num">1024</span>, tools=tools,
    messages=[{<span class="str">"role"</span>: <span class="str">"user"</span>, <span class="str">"content"</span>: <span class="str">"Research the latest in fusion energy"</span>}]
)</code></pre>
  </div>

  <div class="section">
    <h2>Endpoints &amp; Pricing</h2>
    <div class="endpoints-grid">
      <div class="endpoint-pill"><code>/research</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/write</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/code</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/analyze</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/translate</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/summarize</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/social</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/extract</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/qa</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/classify</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/sentiment</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/keywords</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/compare</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/transform</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/chat</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/plan</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/decide</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/proofread</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/explain</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/questions</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/outline</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/email</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/sql</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/regex</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/mock</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/score</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/timeline</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/action</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/pitch</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/debate</code> <span class="price">$0.02</span></div>
      <div class="endpoint-pill"><code>/headline</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/fact</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/rewrite</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/tag</code> <span class="price">$0.01</span></div>
      <div class="endpoint-pill"><code>/batch</code> <span class="price">$0.10</span></div>
      <div class="endpoint-pill"><code>/pipeline</code> <span class="price">$0.15</span></div>
      <div class="endpoint-pill"><code>/preview</code> <span class="price" style="color:#3fb950">FREE</span></div>
    </div>
  </div>

  <div class="link-row">
    <a href="/discover">Full manifest (JSON)</a>
    <a href="/openapi.json">OpenAPI spec</a>
    <a href="/preview">Free preview</a>
    <a href="https://mcp.aipaygent.xyz/mcp">MCP endpoint</a>
    <a href="https://pypi.org/project/aipaygent-mcp/">PyPI package</a>
    <a href="https://x402.org">x402 protocol</a>
  </div>

</div>
</body>
</html>'''
    from flask import Response, make_response
    resp = make_response(Response(html, mimetype="text/html"))
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ─── New AI Capability Endpoints ─────────────────────────────────────────────

def vision_inner(image_url, question="Describe this image in detail", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "url", "url": image_url}},
            {"type": "text", "text": question},
        ],
    }], max_tokens=1024)
    return {"image_url": image_url, "question": question, "analysis": r["text"], "model": r["model"]}


def rag_inner(documents, query, model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Documents:\n{documents}\n\n"
            f"Query: {query}\n\n"
            f'Return JSON: {{"answer": "str", "confidence": 0.0-1.0, '
            f'"citations": ["relevant quotes"], "cannot_answer": false}}'
        ),
    }], system="Answer using ONLY the provided documents. Never hallucinate. Cite specific document sections.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"answer": r["text"]}
    return {**parsed, "model": r["model"]}


def diagram_inner(description, diagram_type="flowchart", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Create a {diagram_type} Mermaid diagram for: {description}\n"
            f'Return JSON: {{"mermaid": "valid mermaid code block", "title": "str", "description": "str"}}'
        ),
    }], system="You generate valid Mermaid diagram syntax. Always respond with valid JSON only.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"mermaid": r["text"]}
    return {**parsed, "model": r["model"]}


def json_schema_inner(description, example="", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": f"Generate JSON Schema for: {description}\nExample data: {example}\nReturn the complete JSON Schema object.",
    }], system="You are a JSON Schema expert. Generate valid JSON Schema draft-07. Always respond with valid JSON only.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"schema": r["text"]}
    return {**parsed, "model": r["model"]}


def test_cases_inner(code_or_description, language="python", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Generate comprehensive test cases for:\n{code_or_description}\n"
            f'Return JSON: {{"test_cases": [{{"name": "str", "input": "str", "expected": "str", "edge_case": true}}], '
            f'"coverage_notes": "str", "suggested_framework": "str"}}'
        ),
    }], system=f"You are a {language} testing expert. Always respond with valid JSON only.", max_tokens=1500)
    parsed = parse_json_from_claude(r["text"]) or {"test_cases": r["text"]}
    return {**parsed, "model": r["model"]}


def workflow_inner(goal, available_data="", model="claude-sonnet"):
    r = call_model(model, [{"role": "user", "content": f"Goal: {goal}\n\nAvailable data:\n{available_data}"}],
        system="You are an autonomous agent. Break complex goals into sub-tasks, reason through each, and produce a comprehensive final answer. Show your reasoning, then give a clean result.",
        max_tokens=4096)
    return {"goal": goal, "result": r["text"], "model": r["model"]}


@app.route("/vision", methods=["POST"])
def vision():
    data = request.get_json() or {}
    image_url = data.get("url") or data.get("image_url")
    question = data.get("question", "Describe this image in detail")
    if not image_url:
        return jsonify({"error": "url required"}), 400
    try:
        result = vision_inner(image_url, question, model=data.get("model", "claude-haiku"))
        log_payment("/vision", 0.05, request.remote_addr)
        return jsonify(agent_response(result, "/vision"))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/rag", methods=["POST"])
def rag():
    data = request.get_json() or {}
    documents = data.get("documents", "")
    query = data.get("query", "")
    if not documents or not query:
        return jsonify({"error": "documents and query required"}), 400
    result = rag_inner(documents, query, model=data.get("model", "claude-haiku"))
    log_payment("/rag", 0.05, request.remote_addr)
    return jsonify(agent_response({"query": query, **result}, "/rag"))


@app.route("/diagram", methods=["POST"])
def diagram():
    data = request.get_json() or {}
    description = data.get("description", "")
    diagram_type = data.get("type", "flowchart")
    if not description:
        return jsonify({"error": "description required"}), 400
    result = diagram_inner(description, diagram_type, model=data.get("model", "claude-haiku"))
    log_payment("/diagram", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/diagram"))


@app.route("/json-schema", methods=["POST"])
def json_schema_route():
    data = request.get_json() or {}
    description = data.get("description", "")
    example = data.get("example", "")
    if not description:
        return jsonify({"error": "description required"}), 400
    result = json_schema_inner(description, example, model=data.get("model", "claude-haiku"))
    log_payment("/json-schema", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/json-schema"))


@app.route("/test-cases", methods=["POST"])
def test_cases_route():
    data = request.get_json() or {}
    code_or_desc = data.get("code") or data.get("description", "")
    language = data.get("language", "python")
    if not code_or_desc:
        return jsonify({"error": "code or description required"}), 400
    result = test_cases_inner(code_or_desc, language, model=data.get("model", "claude-haiku"))
    log_payment("/test-cases", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/test-cases"))


@app.route("/workflow", methods=["POST"])
def workflow_route():
    data = request.get_json() or {}
    goal = data.get("goal", "")
    available_data = data.get("data", data.get("context", ""))
    if not goal:
        return jsonify({"error": "goal required"}), 400
    result = workflow_inner(goal, available_data, model=data.get("model", "claude-sonnet"))
    log_payment("/workflow", 0.20, request.remote_addr)
    return jsonify(agent_response(result, "/workflow"))


# ─── Agent Memory Endpoints ────────────────────────────────────────────────

def _resolve_agent_id(data):
    """Resolve agent_id from JWT (verified) or request body (unverified)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ey"):
        try:
            payload = verify_jwt(auth[7:])
            return payload["agent_id"], True
        except Exception:
            pass
    return data.get("agent_id", ""), False


@app.route("/memory/set", methods=["POST"])
def memory_set_route():
    data = request.get_json() or {}
    agent_id, verified = _resolve_agent_id(data)
    key = data.get("key", "")
    value = data.get("value")
    tags = data.get("tags", [])
    if not agent_id or not key or value is None:
        return jsonify({"error": "agent_id, key, and value required (or use JWT auth)"}), 400
    result = memory_set(agent_id, key, value, tags if isinstance(tags, list) else [tags])
    log_payment("/memory/set", 0.01, request.remote_addr)
    return jsonify(agent_response({**result, "verified": verified}, "/memory/set"))


@app.route("/memory/get", methods=["POST"])
def memory_get_route():
    data = request.get_json() or {}
    agent_id, verified = _resolve_agent_id(data)
    key = data.get("key", "")
    if not agent_id or not key:
        return jsonify({"error": "agent_id and key required (or use JWT auth)"}), 400
    result = memory_get(agent_id, key)
    log_payment("/memory/get", 0.01, request.remote_addr)
    if not result:
        return jsonify({"error": "not_found", "agent_id": agent_id, "key": key}), 404
    return jsonify(agent_response({**result, "verified": verified}, "/memory/get"))


@app.route("/memory/search", methods=["POST"])
def memory_search_route():
    data = request.get_json() or {}
    agent_id, verified = _resolve_agent_id(data)
    query = data.get("query", "")
    if not agent_id or not query:
        return jsonify({"error": "agent_id and query required (or use JWT auth)"}), 400
    results = memory_search(agent_id, query)
    log_payment("/memory/search", 0.02, request.remote_addr)
    return jsonify(agent_response({"agent_id": agent_id, "query": query, "results": results, "count": len(results), "verified": verified}, "/memory/search"))


@app.route("/memory/clear", methods=["POST"])
def memory_clear_route():
    data = request.get_json() or {}
    agent_id, verified = _resolve_agent_id(data)
    if not agent_id:
        return jsonify({"error": "agent_id required (or use JWT auth)"}), 400
    deleted = memory_clear(agent_id)
    log_payment("/memory/clear", 0.01, request.remote_addr)
    return jsonify(agent_response({"agent_id": agent_id, "deleted": deleted, "verified": verified}, "/memory/clear"))


# ─── Agent Identity (wallet auth) ─────────────────────────────────────────

@app.route("/agents/challenge", methods=["POST"])
def agent_challenge():
    """Step 1: Request a challenge to prove wallet ownership."""
    data = request.get_json() or {}
    wallet = data.get("wallet_address", "")
    if not wallet:
        return jsonify({"error": "wallet_address required"}), 400
    ch = generate_challenge(wallet)
    return jsonify(ch)


@app.route("/agents/verify", methods=["POST"])
def agent_verify():
    """Step 2: Submit signed challenge to get JWT."""
    data = request.get_json() or {}
    nonce = data.get("nonce", "")
    signature = data.get("signature", "")
    chain = data.get("chain", "evm")
    if not nonce or not signature:
        return jsonify({"error": "nonce and signature required"}), 400
    try:
        result = verify_challenge(nonce, signature, chain)
        # Auto-register in agent registry if not exists
        try:
            register_agent(
                result["agent_id"],
                data.get("name", f"agent-{result['agent_id'][:8]}"),
                data.get("description", ""),
                data.get("capabilities", ""),
                data.get("endpoint", ""),
            )
        except Exception:
            pass
        return jsonify(result)
    except (InvalidSignatureError, ChallengeExpiredError) as e:
        return jsonify({"error": str(e)}), 401


@app.route("/agents/me", methods=["GET"])
def agent_me():
    """Get current agent profile (requires JWT)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ey"):
        return jsonify({"error": "JWT required. Use /agents/challenge + /agents/verify first."}), 401
    try:
        payload = verify_jwt(auth[7:])
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": f"Invalid token: {e}"}), 401


# ─── Agent Registry (free) ────────────────────────────────────────────────

@app.route("/agents/register", methods=["POST"])
def agents_register():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "")
    name = data.get("name", "")
    description = data.get("description", "")
    capabilities = data.get("capabilities", [])
    endpoint = data.get("endpoint")
    if not agent_id or not name:
        return jsonify({"error": "agent_id and name required"}), 400
    result = register_agent(agent_id, name, description, capabilities, endpoint)
    return jsonify({"registered": True, "agent_id": agent_id, "listing": f"https://api.aipaygent.xyz/agents"})


@app.route("/agents", methods=["GET"])
def agents_list():
    agents = list_agents()
    return jsonify({"agents": agents, "count": len(agents), "_meta": {"endpoint": "/agents", "ts": datetime.utcnow().isoformat() + "Z"}})


@app.route("/agents/search", methods=["GET"])
def agents_search():
    """Search agents by capability, name, or description."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    agents = list_agents()
    results = []
    q_lower = q.lower()
    for a in agents:
        score = 0
        if q_lower in (a.get("name", "") or "").lower():
            score += 3
        if q_lower in (a.get("capabilities", "") or "").lower():
            score += 2
        if q_lower in (a.get("description", "") or "").lower():
            score += 1
        if score > 0:
            results.append({**a, "_relevance": score})
    results.sort(key=lambda x: x["_relevance"], reverse=True)
    return jsonify({"query": q, "results": results[:20]})


@app.route("/agents/<agent_id>/portfolio", methods=["GET"])
def agent_portfolio(agent_id):
    """Get agent's full portfolio: reputation, marketplace listings."""
    rep = get_reputation(agent_id)
    all_listings, _ = marketplace_get_services(per_page=200)
    agent_listings = [l for l in all_listings if l.get("agent_id") == agent_id]
    return jsonify({
        "agent_id": agent_id,
        "reputation": rep,
        "marketplace_listings": agent_listings,
        "verified": False,
    })


@app.route("/catalog", methods=["GET"])
def catalog():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    category = request.args.get("category")
    source = request.args.get("source")
    min_score = request.args.get("min_score", type=float)
    free_only = request.args.get("free_only", "").lower() in ("1", "true", "yes")
    apis, total = get_all_apis(page=page, per_page=per_page, category=category,
                               source=source, min_score=min_score, free_only=free_only)
    return jsonify({
        "apis": apis,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "_meta": {"endpoint": "/catalog", "ts": datetime.utcnow().isoformat() + "Z"},
    })


@app.route("/catalog/<int:api_id>", methods=["GET"])
def catalog_item(api_id):
    api = get_api(api_id)
    if not api:
        return jsonify({"error": "not_found"}), 404
    return jsonify(api)


@app.route("/run-discovery", methods=["POST"])
def run_discovery():
    job_id = str(uuid.uuid4())[:8]
    _discovery_jobs[job_id] = {"status": "running", "started_at": datetime.utcnow().isoformat()}

    def _run():
        try:
            results = run_all_agents(claude)
            _discovery_jobs[job_id].update({"status": "completed", "results": results})
        except Exception as e:
            _discovery_jobs[job_id].update({"status": "error", "error": str(e)})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "status": "running",
                    "check": f"/discovery-status/{job_id}"})


@app.route("/discovery-status/<job_id>", methods=["GET"])
def discovery_status(job_id):
    job = _discovery_jobs.get(job_id)
    if not job:
        return jsonify({"error": "job_not_found", "hint": "POST /run-discovery to start a new job"}), 404
    return jsonify({"job_id": job_id, **job, "recent_runs": get_recent_runs(5)})


@app.route("/api-call", methods=["POST"])
def api_call():
    data = request.get_json() or {}
    api_id = data.get("api_id")
    endpoint = data.get("endpoint", "/")
    params = data.get("params", {})
    api_key = data.get("api_key")
    enrich = data.get("enrich", False)

    if not api_id:
        return jsonify({"error": "api_id required"}), 400

    api = get_api(api_id)
    if not api:
        return jsonify({"error": "api_not_found", "hint": "GET /catalog to browse available APIs"}), 404

    url = api["base_url"].rstrip("/") + "/" + endpoint.lstrip("/")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = _requests.get(url, params=params, headers=headers, timeout=15)
        result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        enrichment = None
        if enrich and isinstance(result, (dict, list)):
            llm_result, llm_err = _call_llm(
                [{"role": "user", "content": f"Summarize this API response in 2-3 sentences:\n{json.dumps(result)[:2000]}"}],
                max_tokens=512, endpoint="/api-call",
            )
            if not llm_err:
                enrichment = llm_result["text"]
        log_payment("/api-call", 0.05, request.remote_addr)
        return jsonify(agent_response({
            "api_name": api["name"],
            "url": url,
            "status_code": resp.status_code,
            "result": result,
            "enrichment": enrichment,
        }, "/api-call"))
    except Exception as e:
        return jsonify({"error": "proxy_failed", "message": str(e)}), 502


@app.route("/scrape/google-maps", methods=["POST"])
def scrape_google_maps():
    data = request.get_json() or {}
    query = data.get("query") or data.get("location")
    if not query:
        return jsonify({"error": "query required (e.g. 'restaurants in NYC')"}), 400
    max_items = min(int(data.get("max_items", 5)), 10)
    run_input = {"searchStringsArray": [query], "maxCrawledPlacesPerSearch": max_items}
    try:
        results = run_actor_sync("nwua9Gu5YrADL7ZDj", run_input, max_items=max_items)
        log_payment("/scrape/google-maps", 0.10, request.remote_addr)
        return jsonify(agent_response({"query": query, "results": results, "count": len(results)}, "/scrape/google-maps"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


@app.route("/scrape/instagram", methods=["POST"])
def scrape_instagram():
    data = request.get_json() or {}
    username = data.get("username")
    if not username:
        return jsonify({"error": "username required"}), 400
    max_items = min(int(data.get("max_items", 5)), 20)
    run_input = {"username": [username], "resultsLimit": max_items}
    try:
        results = run_actor_sync("shu8hvrXbJbY3Eb9W", run_input, max_items=max_items)
        log_payment("/scrape/instagram", 0.05, request.remote_addr)
        return jsonify(agent_response({"username": username, "results": results, "count": len(results)}, "/scrape/instagram"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


@app.route("/scrape/tweets", methods=["POST"])
def scrape_tweets():
    data = request.get_json() or {}
    query = data.get("query")
    if not query:
        return jsonify({"error": "query required"}), 400
    max_items = min(int(data.get("max_items", 25)), 50)
    run_input = {"searchTerms": [query], "maxItems": max_items}
    try:
        results = run_actor_sync("61RPP7dywgiy0JPD0", run_input, max_items=max_items)
        log_payment("/scrape/tweets", 0.05, request.remote_addr)
        return jsonify(agent_response({"query": query, "results": results, "count": len(results)}, "/scrape/tweets"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


@app.route("/scrape/linkedin", methods=["POST"])
def scrape_linkedin():
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "url required (LinkedIn profile URL)"}), 400
    run_input = {"profileUrls": [url]}
    try:
        results = run_actor_sync("2SyF0bVxmgGr8IVCZ", run_input, max_items=5)
        log_payment("/scrape/linkedin", 0.15, request.remote_addr)
        return jsonify(agent_response({"url": url, "results": results, "count": len(results)}, "/scrape/linkedin"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


@app.route("/scrape/youtube", methods=["POST"])
def scrape_youtube():
    data = request.get_json() or {}
    query = data.get("query")
    if not query:
        return jsonify({"error": "query required"}), 400
    max_items = min(int(data.get("max_items", 5)), 20)
    run_input = {"searchKeywords": query, "maxResults": max_items}
    try:
        results = run_actor_sync("h7sDV53CddomktSi5", run_input, max_items=max_items)
        log_payment("/scrape/youtube", 0.05, request.remote_addr)
        return jsonify(agent_response({"query": query, "results": results, "count": len(results)}, "/scrape/youtube"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


@app.route("/scrape/web", methods=["POST"])
def scrape_web():
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "url required"}), 400
    max_pages = min(int(data.get("max_pages", 5)), 20)
    run_input = {"startUrls": [{"url": url}], "maxCrawlPages": max_pages}
    try:
        results = run_actor_sync("aYG0l9s7dbB7j3gbS", run_input, max_items=max_pages)
        log_payment("/scrape/web", 0.05, request.remote_addr)
        return jsonify(agent_response({"url": url, "results": results, "count": len(results)}, "/scrape/web"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


@app.route("/scrape/tiktok", methods=["POST"])
def scrape_tiktok():
    data = request.get_json() or {}
    username = data.get("username")
    if not username:
        return jsonify({"error": "username required"}), 400
    max_items = min(int(data.get("max_items", 5)), 20)
    run_input = {"profiles": [username], "resultsPerPage": max_items}
    try:
        results = run_actor_sync("GdWCkxBtKWOsKjdch", run_input, max_items=max_items)
        log_payment("/scrape/tiktok", 0.05, request.remote_addr)
        return jsonify(agent_response({"username": username, "results": results, "count": len(results)}, "/scrape/tiktok"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


@app.route("/scrape/facebook-ads", methods=["POST"])
def scrape_facebook_ads():
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "url required (Facebook Ad Library URL)"}), 400
    max_items = min(int(data.get("max_items", 10)), 50)
    run_input = {"adLibraryUrl": url, "maxResults": max_items}
    try:
        results = run_actor_sync("JJghSZmShuco4j9gJ", run_input, max_items=max_items)
        log_payment("/scrape/facebook-ads", 0.10, request.remote_addr)
        return jsonify(agent_response({"url": url, "results": results, "count": len(results)}, "/scrape/facebook-ads"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


@app.route("/scrape/actor", methods=["POST"])
def scrape_actor():
    data = request.get_json() or {}
    actor_id = data.get("actor_id")
    run_input = data.get("run_input", {})
    max_items = min(int(data.get("max_items", 10)), 50)
    if not actor_id:
        return jsonify({"error": "actor_id required (e.g. 'aYG0l9s7dbB7j3gbS')"}), 400
    try:
        results = run_actor_sync(actor_id, run_input, max_items=max_items)
        log_payment("/scrape/actor", 0.10, request.remote_addr)
        return jsonify(agent_response({"actor_id": actor_id, "results": results, "count": len(results)}, "/scrape/actor"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


# ── Free Honeypot Endpoints ───────────────────────────────────────────────────

@app.route("/free/time", methods=["GET"])
def free_time():
    """Free endpoint: current UTC time + timezone conversions. No payment needed."""
    from datetime import timezone
    now_utc = datetime.utcnow()
    return jsonify({
        "utc": now_utc.isoformat() + "Z",
        "unix": int(now_utc.replace(tzinfo=timezone.utc).timestamp()),
        "date": now_utc.strftime("%Y-%m-%d"),
        "time": now_utc.strftime("%H:%M:%S"),
        "day_of_week": now_utc.strftime("%A"),
        "week_number": int(now_utc.strftime("%W")),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


@app.route("/free/uuid", methods=["GET"])
def free_uuid():
    """Free endpoint: generate UUIDs. No payment needed."""
    import uuid
    return jsonify({
        "uuid4": str(uuid.uuid4()),
        "uuid4_list": [str(uuid.uuid4()) for _ in range(5)],
        "uuid1": str(uuid.uuid1()),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


@app.route("/free/ip", methods=["GET"])
def free_ip():
    """Free endpoint: caller's IP info. No payment needed."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    return jsonify({
        "ip": ip,
        "forwarded_for": request.headers.get("X-Forwarded-For"),
        "user_agent": request.headers.get("User-Agent"),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


@app.route("/free/hash", methods=["GET", "POST"])
def free_hash():
    """Free endpoint: hash a string. No payment needed."""
    import hashlib
    text = ""
    if request.method == "POST":
        data = request.get_json() or {}
        text = data.get("text", "")
    else:
        text = request.args.get("text", "hello world")
    text_bytes = text.encode("utf-8")
    return jsonify({
        "input": text,
        "md5": hashlib.md5(text_bytes).hexdigest(),
        "sha1": hashlib.sha1(text_bytes).hexdigest(),
        "sha256": hashlib.sha256(text_bytes).hexdigest(),
        "sha512": hashlib.sha512(text_bytes).hexdigest(),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


@app.route("/free/base64", methods=["GET", "POST"])
def free_base64():
    """Free endpoint: encode/decode base64. No payment needed."""
    import base64 as _b64
    data = request.get_json() or {} if request.method == "POST" else {}
    text = data.get("text") or request.args.get("text", "")
    decode_text = data.get("decode") or request.args.get("decode", "")
    result = {}
    if text:
        result["encoded"] = _b64.b64encode(text.encode()).decode()
    if decode_text:
        try:
            result["decoded"] = _b64.b64decode(decode_text).decode()
        except Exception:
            result["decode_error"] = "invalid base64"
    result["_meta"] = {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    return jsonify(result)


@app.route("/free/random", methods=["GET"])
def free_random():
    """Free endpoint: random numbers, choices, and samples."""
    import random
    import string
    n = min(int(request.args.get("n", 5)), 100)
    min_val = int(request.args.get("min", 1))
    max_val = int(request.args.get("max", 100))
    return jsonify({
        "integers": [random.randint(min_val, max_val) for _ in range(n)],
        "float": random.random(),
        "bool": random.choice([True, False]),
        "shuffle_example": random.sample(list(range(1, 11)), 10),
        "random_string": "".join(random.choices(string.ascii_letters + string.digits, k=16)),
        "_meta": {"free": True, "note": "Visit /discover for 80+ paid AI endpoints"}
    })


# ── SDK Code Generator ─────────────────────────────────────────────────────────

@app.route("/sdk/code", methods=["GET"])
def sdk_code():
    """Return copy-paste SDK code in Python, JavaScript, or cURL as JSON."""
    lang = request.args.get("lang", "python").lower()
    endpoint = request.args.get("endpoint", "/research")
    base_url = "https://api.aipaygent.xyz"

    if lang in ("python", "py"):
        code = f'''import requests

# AiPayGent Python SDK — copy-paste ready
# More endpoints: {base_url}/discover

def call_aipaygent(endpoint: str, payload: dict, x402_token: str = None) -> dict:
    """Call any AiPayGent endpoint. x402_token required for paid endpoints."""
    headers = {{"Content-Type": "application/json"}}
    if x402_token:
        headers["X-Payment"] = x402_token
    resp = requests.post(f"{base_url}{{endpoint}}", json=payload, headers=headers)
    if resp.status_code == 402:
        payment_info = resp.json()
        raise ValueError(f"Payment required: {{payment_info}}")
    resp.raise_for_status()
    return resp.json()

# Example: research
result = call_aipaygent("{endpoint}", {{"query": "latest AI agent frameworks 2026"}})
print(result["result"])

# Free endpoints (no payment needed)
import requests
print(requests.get("{base_url}/free/time").json())     # UTC time
print(requests.get("{base_url}/free/uuid").json())     # UUID
print(requests.get("{base_url}/free/ip").json())       # Your IP
print(requests.get("{base_url}/catalog").json())       # API catalog
'''
    elif lang in ("javascript", "js", "typescript", "ts"):
        code = f'''// AiPayGent JavaScript SDK — copy-paste ready
// More endpoints: {base_url}/discover

const BASE = "{base_url}";

async function callAiPayGent(endpoint, payload, x402Token = null) {{
  const headers = {{ "Content-Type": "application/json" }};
  if (x402Token) headers["X-Payment"] = x402Token;
  const res = await fetch(`${{BASE}}${{endpoint}}`, {{
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  }});
  if (res.status === 402) {{
    const info = await res.json();
    throw new Error(`Payment required: ${{JSON.stringify(info)}}`);
  }}
  if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
  return res.json();
}}

// Example: research
const result = await callAiPayGent("{endpoint}", {{ query: "latest AI agent frameworks 2026" }});
console.log(result.result);

// Free endpoints (no payment needed)
const time = await fetch(`${{BASE}}/free/time`).then(r => r.json());
const catalog = await fetch(`${{BASE}}/catalog`).then(r => r.json());
console.log(time, catalog);
'''
    elif lang in ("curl", "bash", "sh"):
        code = f'''#!/bin/bash
# AiPayGent cURL examples — copy-paste ready
BASE="{base_url}"

# Free endpoints
curl "$BASE/free/time"
curl "$BASE/free/uuid"
curl "$BASE/catalog?min_score=7"

# Paid endpoints (replace X_PAYMENT with valid x402 token)
curl -X POST "$BASE{endpoint}" \\
  -H "Content-Type: application/json" \\
  -H "X-Payment: $X_PAYMENT" \\
  -d \'{{"query": "latest AI agent frameworks 2026"}}\'

# List all 80+ endpoints
curl "$BASE/discover" | python3 -m json.tool
'''
    else:
        return jsonify({"error": f"Unknown lang '{lang}'. Use: python, javascript, curl"}), 400

    return jsonify({
        "lang": lang,
        "endpoint": endpoint,
        "code": code,
        "base_url": base_url,
        "docs": f"{base_url}/discover",
        "_meta": {"free": True}
    })


@app.route("/sitemap.xml", methods=["GET"])
def sitemap():
    """XML sitemap — includes static pages AND all blog posts for Google/Bing."""
    base_url = "https://api.aipaygent.xyz"
    now = datetime.utcnow().strftime("%Y-%m-%d")
    static_pages = [
        ("/", "daily", "1.0"),
        ("/discover", "weekly", "0.9"),
        ("/blog", "daily", "0.9"),
        ("/buy-credits", "monthly", "0.8"),
        ("/preview", "weekly", "0.7"),
        ("/openapi.json", "weekly", "0.6"),
        ("/llms.txt", "weekly", "0.6"),
        ("/sdk", "weekly", "0.6"),
        ("/catalog", "weekly", "0.5"),
        ("/marketplace", "weekly", "0.5"),
        ("/agents", "daily", "0.5"),
        ("/changelog", "daily", "0.7"),
        ("/stats", "daily", "0.4"),
        ("/health", "hourly", "0.3"),
    ]
    urls_xml = "\n".join(
        f'  <url><loc>{base_url}{p}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority><lastmod>{now}</lastmod></url>'
        for p, freq, pri in static_pages
    )
    # Add all blog posts with their actual generation date
    try:
        for post in list_blog_posts():
            slug = post["slug"]
            date = post.get("generated_at", now)[:10]
            urls_xml += f'\n  <url><loc>{base_url}/blog/{slug}</loc><changefreq>monthly</changefreq><priority>0.8</priority><lastmod>{date}</lastmod></url>'
    except Exception:
        pass
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
{urls_xml}
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml"}


# ── Agent Marketplace ──────────────────────────────────────────────────────────

@app.route("/marketplace", methods=["GET"])
def marketplace_browse():
    """Browse the agent marketplace — free, no payment required."""
    category = request.args.get("category")
    max_price = float(request.args.get("max_price", 9999))
    min_price = float(request.args.get("min_price", 0))
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 50)
    listings, total = marketplace_get_services(
        category=category or None,
        max_price=max_price if max_price < 9999 else None,
        min_price=min_price if min_price > 0 else None,
        page=page, per_page=per_page
    )
    return jsonify({
        "listings": listings,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "_meta": {"free": True, "description": "Agent-to-agent marketplace — list your services, earn x402 payments"}
    })


@app.route("/marketplace/list", methods=["POST"])
def marketplace_list():
    """Register your agent's service in the marketplace — free to list."""
    data = request.get_json() or {}
    required = ["agent_id", "name", "endpoint", "price_usd"]
    for f in required:
        if not data.get(f):
            return jsonify({"error": f"'{f}' required"}), 400
    result = marketplace_list_service(
        agent_id=data["agent_id"],
        name=data["name"][:255],
        description=data.get("description", "")[:500],
        endpoint=data["endpoint"],
        price_usd=float(data["price_usd"]),
        category=data.get("category", "general"),
        capabilities=data.get("capabilities", []),
    )
    return jsonify(result)


@app.route("/marketplace/listing/<listing_id>", methods=["GET"])
def marketplace_get(listing_id):
    """Get a single marketplace listing."""
    listing = marketplace_get_service(listing_id)
    if not listing:
        return jsonify({"error": "listing not found"}), 404
    return jsonify(listing)


@app.route("/marketplace/delist", methods=["POST"])
def marketplace_delist():
    """Remove your listing from the marketplace."""
    data = request.get_json() or {}
    if not data.get("listing_id") or not data.get("agent_id"):
        return jsonify({"error": "listing_id and agent_id required"}), 400
    removed = marketplace_deregister(data["listing_id"], data["agent_id"])
    return jsonify({"removed": removed})


@app.route("/marketplace/call", methods=["POST"])
def marketplace_call():
    """Proxy-call an agent marketplace listing. Requires x402 payment."""
    data = request.get_json() or {}
    listing_id = data.get("listing_id")
    if not listing_id:
        return jsonify({"error": "listing_id required"}), 400
    listing = marketplace_get_service(listing_id)
    if not listing:
        return jsonify({"error": "listing not found"}), 404
    if not listing.get("is_active"):
        return jsonify({"error": "listing is inactive"}), 410

    payload = data.get("payload", {})
    endpoint = listing["endpoint"]
    try:
        resp = _requests.post(endpoint, json=payload, timeout=60,
                              headers={"User-Agent": "AiPayGent-Marketplace/1.0"})
        marketplace_increment_calls(listing_id)
        log_payment("/marketplace/call", 0.05, request.remote_addr)
        return jsonify(agent_response({
            "listing_id": listing_id,
            "listing_name": listing["name"],
            "status_code": resp.status_code,
            "result": resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else resp.text[:2000],
        }, "/marketplace/call"))
    except Exception as e:
        return jsonify({"error": "proxy_failed", "message": str(e)}), 502


# ── Chain Endpoint ─────────────────────────────────────────────────────────────

# Map step names to _inner functions for the chain endpoint
_CHAIN_HANDLERS = {
    "research": lambda p: research_inner(p.get("query", ""), model=p.get("model", "claude-haiku")),
    "summarize": lambda p: summarize_inner(p.get("text", ""), p.get("format", "bullets"), model=p.get("model", "claude-haiku")),
    "analyze": lambda p: analyze_inner(p.get("text", ""), p.get("question", ""), model=p.get("model", "claude-haiku")),
    "translate": lambda p: translate_inner(p.get("text", ""), p.get("language", "English"), model=p.get("model", "claude-haiku")),
    "sentiment": lambda p: sentiment_inner(p.get("text", ""), model=p.get("model", "claude-haiku")),
    "keywords": lambda p: keywords_inner(p.get("text", ""), int(p.get("n", 10)), model=p.get("model", "claude-haiku")),
    "classify": lambda p: classify_inner(p.get("text", ""), p.get("categories", []), model=p.get("model", "claude-haiku")),
    "rewrite": lambda p: rewrite_inner(p.get("text", ""), p.get("audience", "general"), p.get("tone", "professional"), model=p.get("model", "claude-haiku")),
    "extract": lambda p: extract_inner(p.get("text", ""), p.get("schema_desc", ""), p.get("fields", []), model=p.get("model", "claude-haiku")),
    "qa": lambda p: qa_inner(p.get("context", ""), p.get("question", ""), model=p.get("model", "claude-haiku")),
    "compare": lambda p: compare_inner(p.get("text_a", ""), p.get("text_b", ""), p.get("focus", ""), model=p.get("model", "claude-haiku")),
    "outline": lambda p: outline_inner(p.get("topic", ""), int(p.get("depth", 2)), model=p.get("model", "claude-haiku")),
    "diagram": lambda p: diagram_inner(p.get("description", ""), p.get("diagram_type", "flowchart"), model=p.get("model", "claude-haiku")),
    "json_schema": lambda p: json_schema_inner(p.get("description", ""), p.get("example", {}), model=p.get("model", "claude-haiku")),
    "workflow": lambda p: workflow_inner(p.get("goal", ""), p.get("available_data", {}), model=p.get("model", "claude-sonnet")),
}


@app.route("/chain", methods=["POST"])
def chain_endpoint():
    """Chain up to 5 AI operations in sequence. Output of each step feeds the next."""
    data = request.get_json() or {}
    steps = data.get("steps", [])
    if not steps:
        return jsonify({"error": "steps array required"}), 400
    if len(steps) > 5:
        return jsonify({"error": "maximum 5 steps per chain"}), 400

    results = []
    context = {}  # carries forward between steps

    for i, step in enumerate(steps):
        name = step.get("action")
        if not name or name not in _CHAIN_HANDLERS:
            return jsonify({
                "error": f"step {i}: unknown action '{name}'",
                "available": list(_CHAIN_HANDLERS.keys())
            }), 400

        # Allow steps to reference previous result via {{prev_result}}
        params = step.get("params", {})
        if context.get("last_result"):
            for k, v in params.items():
                if isinstance(v, str) and "{{prev_result}}" in v:
                    params[k] = v.replace("{{prev_result}}", str(context["last_result"]))

        try:
            out = _CHAIN_HANDLERS[name](params)
            step_result = {"step": i + 1, "action": name, "result": out}
            results.append(step_result)
            # Extract text result for next step context
            if isinstance(out, dict):
                context["last_result"] = out.get("result") or out.get("text") or out.get("summary") or str(out)
            else:
                context["last_result"] = str(out)
        except Exception as e:
            return jsonify({"error": f"step {i} ({name}) failed: {str(e)}", "completed_steps": results}), 500

    log_payment("/chain", 0.25, request.remote_addr)
    return jsonify(agent_response({
        "steps_completed": len(results),
        "chain": results,
        "final_result": results[-1]["result"] if results else None,
    }, "/chain"))


# ── Real-Time Data (FREE) ──────────────────────────────────────────────────────

@app.route("/data/weather", methods=["GET"])
def data_weather():
    city = request.args.get("city", "London")
    ck = f"weather:{city.lower()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        geo = _requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=8,
        ).json()
        results = geo.get("results", [])
        if not results:
            return jsonify({"error": "city_not_found", "city": city}), 404
        loc = results[0]
        weather = _requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "current_weather": "true",
                "hourly": "temperature_2m,precipitation_probability",
                "forecast_days": 1,
            },
            timeout=8,
        ).json()
        cw = weather.get("current_weather", {})
        result = {
            "city": loc.get("name"),
            "country": loc.get("country"),
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "temperature_c": cw.get("temperature"),
            "windspeed_kmh": cw.get("windspeed"),
            "weather_code": cw.get("weathercode"),
            "is_day": cw.get("is_day"),
            "time": cw.get("time"),
            "_meta": {"free": True, "source": "open-meteo.com"},
        }
        _cache_set(ck, result, 600)  # 10 min
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "weather_fetch_failed", "message": str(e)}), 502


@app.route("/data/crypto", methods=["GET"])
def data_crypto():
    symbol = request.args.get("symbol", "bitcoin,ethereum")
    ck = f"crypto:{symbol}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": symbol,
                "vs_currencies": "usd,eur,gbp",
                "include_24hr_change": "true",
                "include_market_cap": "true",
            },
            timeout=8,
        )
        data = resp.json()
        result = {"prices": data, "symbols": symbol.split(","), "_meta": {"free": True, "source": "coingecko.com"}}
        _cache_set(ck, result, 120)  # 2 min
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "crypto_fetch_failed", "message": str(e)}), 502


@app.route("/data/exchange-rates", methods=["GET"])
def data_exchange_rates():
    base = request.args.get("base", "USD").upper()
    ck = f"fx:{base}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://api.exchangerate-api.com/v4/latest/{base}",
            timeout=8,
        )
        data = resp.json()
        result = {
            "base": base,
            "date": data.get("date"),
            "rates": data.get("rates", {}),
            "_meta": {"free": True, "source": "exchangerate-api.com"},
        }
        _cache_set(ck, result, 3600)  # 1 hr
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "exchange_rate_fetch_failed", "message": str(e)}), 502


@app.route("/data/country", methods=["GET"])
def data_country():
    name = request.args.get("name", "")
    if not name:
        return jsonify({"error": "name required (e.g. ?name=France)"}), 400
    ck = f"country:{name.lower()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://restcountries.com/v3.1/name/{name}",
            params={"fields": "name,capital,currencies,languages,population,flags,region,subregion"},
            timeout=8,
        )
        if resp.status_code == 404:
            return jsonify({"error": "country_not_found", "name": name}), 404
        countries = resp.json()
        result = {"results": countries, "count": len(countries), "_meta": {"free": True, "source": "restcountries.com"}}
        _cache_set(ck, result, 86400)  # 24 hr
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "country_fetch_failed", "message": str(e)}), 502


@app.route("/data/ip", methods=["GET"])
def data_ip():
    ip = request.args.get("ip", "")
    target = ip if ip else request.remote_addr
    try:
        resp = _requests.get(f"http://ip-api.com/json/{target}", params={"fields": "status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"}, timeout=8)
        data = resp.json()
        data["_meta"] = {"free": True, "source": "ip-api.com"}
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": "ip_fetch_failed", "message": str(e)}), 502


@app.route("/data/news", methods=["GET"])
def data_news():
    cached = _cache_get("hn_news")
    if cached:
        return jsonify(cached)
    try:
        top_ids = _requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=8,
        ).json()[:10]
        stories = []
        for sid in top_ids:
            item = _requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                timeout=5,
            ).json()
            if item:
                stories.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "score": item.get("score"),
                    "by": item.get("by"),
                    "comments": item.get("descendants", 0),
                })
        result = {"stories": stories, "count": len(stories), "_meta": {"free": True, "source": "hacker-news.firebaseio.com"}}
        _cache_set("hn_news", result, 900)  # 15 min
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "news_fetch_failed", "message": str(e)}), 502


@app.route("/data/stocks", methods=["GET"])
def data_stocks():
    symbol = request.args.get("symbol", "AAPL").upper()
    ck = f"stock:{symbol}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return jsonify({"error": "symbol_not_found", "symbol": symbol}), 404
        meta = result[0].get("meta", {})
        stock_result = {
            "symbol": symbol,
            "currency": meta.get("currency"),
            "price": meta.get("regularMarketPrice"),
            "previous_close": meta.get("previousClose"),
            "market_state": meta.get("marketState"),
            "exchange": meta.get("exchangeName"),
            "_meta": {"free": True, "source": "yahoo finance"},
        }
        _cache_set(ck, stock_result, 300)  # 5 min
        return jsonify(stock_result)
    except Exception as e:
        return jsonify({"error": "stock_fetch_failed", "message": str(e)}), 502


# ── Agent Messaging ────────────────────────────────────────────────────────────

@app.route("/message/send", methods=["POST"])
def message_send():
    data = request.get_json() or {}
    from_agent = data.get("from_agent", "")
    to_agent = data.get("to_agent", "")
    body = data.get("body", "")
    if not from_agent or not to_agent or not body:
        return jsonify({"error": "from_agent, to_agent, and body required"}), 400
    result = send_message(from_agent, to_agent, data.get("subject", ""), body, data.get("thread_id"))
    log_payment("/message/send", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/message/send"))


@app.route("/message/inbox/<agent_id>", methods=["GET"])
def message_inbox(agent_id):
    unread_only = request.args.get("unread_only", "0") in ("1", "true", "yes")
    messages = get_inbox(agent_id, unread_only=unread_only)
    return jsonify({"agent_id": agent_id, "messages": messages, "count": len(messages), "_meta": {"free": True}})


@app.route("/message/reply", methods=["POST"])
def message_reply():
    data = request.get_json() or {}
    msg_id = data.get("msg_id", "")
    from_agent = data.get("from_agent", "")
    body = data.get("body", "")
    if not msg_id or not from_agent or not body:
        return jsonify({"error": "msg_id, from_agent, and body required"}), 400
    # Find original to get thread_id and reply-to agent
    msgs = get_inbox("__lookup__")  # we'll just use send_message with thread_id
    result = send_message(from_agent, data.get("to_agent", ""), data.get("subject", "Re:"), body, thread_id=msg_id)
    log_payment("/message/reply", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/message/reply"))


@app.route("/message/broadcast", methods=["POST"])
def message_broadcast():
    data = request.get_json() or {}
    from_agent = data.get("from_agent", "")
    body = data.get("body", "")
    if not from_agent or not body:
        return jsonify({"error": "from_agent and body required"}), 400
    result = broadcast_message(from_agent, data.get("subject", ""), body)
    log_payment("/message/broadcast", 0.02, request.remote_addr)
    return jsonify(agent_response({"broadcast": True, "result": result}, "/message/broadcast"))


# ── Shared Knowledge Base ──────────────────────────────────────────────────────

@app.route("/knowledge/add", methods=["POST"])
def knowledge_add():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    content = data.get("content", "")
    author_agent = data.get("author_agent", "anonymous")
    if not topic or not content:
        return jsonify({"error": "topic and content required"}), 400
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    result = add_knowledge(topic, content, author_agent, tags)
    log_payment("/knowledge/add", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/knowledge/add"))


@app.route("/knowledge/search", methods=["GET"])
def knowledge_search():
    q = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 10)), 50)
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    results = search_knowledge(q, limit=limit)
    return jsonify({"query": q, "results": results, "count": len(results), "_meta": {"free": True}})


@app.route("/knowledge/trending", methods=["GET"])
def knowledge_trending():
    limit = min(int(request.args.get("limit", 10)), 50)
    topics = get_trending_topics(limit=limit)
    return jsonify({"trending": topics, "_meta": {"free": True}})


@app.route("/knowledge/vote", methods=["POST"])
def knowledge_vote():
    data = request.get_json() or {}
    entry_id = data.get("entry_id", "")
    up = data.get("up", True)
    if not entry_id:
        return jsonify({"error": "entry_id required"}), 400
    result = vote_knowledge(entry_id, up=bool(up))
    return jsonify({**result, "_meta": {"free": True}})


# ── Task Broker ────────────────────────────────────────────────────────────────

@app.route("/task/submit", methods=["POST"])
def task_submit():
    data = request.get_json() or {}
    posted_by = data.get("posted_by", "")
    title = data.get("title", "")
    description = data.get("description", "")
    if not posted_by or not title or not description:
        return jsonify({"error": "posted_by, title, and description required"}), 400
    result = submit_task(
        posted_by, title, description,
        skills_needed=data.get("skills_needed", []),
        reward_usd=float(data.get("reward_usd", 0.0)),
    )
    log_payment("/task/submit", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/task/submit"))


@app.route("/task/browse", methods=["GET"])
def task_browse():
    status = request.args.get("status", "open")
    skill = request.args.get("skill")
    limit = min(int(request.args.get("limit", 20)), 100)
    tasks = browse_tasks(status=status, skill=skill, limit=limit)
    return jsonify({"tasks": tasks, "count": len(tasks), "_meta": {"free": True}})


@app.route("/task/claim", methods=["POST"])
def task_claim():
    data = request.get_json() or {}
    task_id = data.get("task_id", "")
    agent_id = data.get("agent_id", "")
    if not task_id or not agent_id:
        return jsonify({"error": "task_id and agent_id required"}), 400
    success = claim_task(task_id, agent_id)
    return jsonify({"task_id": task_id, "claimed": success, "_meta": {"free": True}})


@app.route("/task/complete", methods=["POST"])
def task_complete():
    data = request.get_json() or {}
    task_id = data.get("task_id", "")
    agent_id = data.get("agent_id", "")
    result = data.get("result", "")
    if not task_id or not agent_id or not result:
        return jsonify({"error": "task_id, agent_id, and result required"}), 400
    success = complete_task(task_id, agent_id, result)
    log_payment("/task/complete", 0.01, request.remote_addr)
    return jsonify(agent_response({"task_id": task_id, "completed": success}, "/task/complete"))


@app.route("/task/<task_id>", methods=["GET"])
def task_get(task_id):
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task_not_found"}), 404
    return jsonify({**task, "_meta": {"free": True}})


# ── Code Execution Sandbox ─────────────────────────────────────────────────────

@app.route("/code/run", methods=["POST"])
def code_run():
    import subprocess
    import time as _time
    data = request.get_json() or {}
    code = data.get("code", "")
    timeout = min(int(data.get("timeout", 10)), 15)
    if not code:
        return jsonify({"error": "code required"}), 400
    if len(code) > 5000:
        return jsonify({"error": "code too long (max 5000 chars)"}), 400
    start = _time.time()
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        elapsed = int((_time.time() - start) * 1000)
        log_payment("/code/run", 0.05, request.remote_addr)
        return jsonify(agent_response({
            "stdout": result.stdout[:3000],
            "stderr": result.stderr[:500],
            "returncode": result.returncode,
            "execution_time_ms": elapsed,
        }, "/code/run"))
    except subprocess.TimeoutExpired:
        return jsonify({"error": "timeout", "message": f"Code exceeded {timeout}s limit"}), 408


# ── Web Search ─────────────────────────────────────────────────────────────────

@app.route("/web/search", methods=["GET", "POST"])
def web_search():
    if request.method == "POST":
        body = request.get_json() or {}
        q = body.get("query", body.get("q", ""))
        n = min(int(body.get("n", 10)), 25)
    else:
        q = request.args.get("q", "")
        n = min(int(request.args.get("n", 10)), 25)
    if not q:
        return jsonify({"error": "q (query) required"}), 400
    try:
        resp = _requests.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10,
        )
        data = resp.json()
        results = [
            {
                "title": t.get("Text", ""),
                "url": t.get("FirstURL", ""),
                "snippet": t.get("Result", ""),
            }
            for t in data.get("RelatedTopics", [])[:n]
            if t.get("FirstURL")
        ]
        log_payment("/web/search", 0.02, request.remote_addr)
        return jsonify(agent_response({
            "query": q,
            "instant_answer": data.get("AbstractText", ""),
            "answer_type": data.get("Type", ""),
            "results": results,
            "count": len(results),
        }, "/web/search"))
    except Exception as e:
        return jsonify({"error": "search_failed", "message": str(e)}), 502


# ── Entity Enrichment ──────────────────────────────────────────────────────────

@app.route("/enrich", methods=["POST"])
def enrich():
    data = request.get_json() or {}
    entity = data.get("entity", "")
    entity_type = data.get("type", "").lower()
    if not entity or not entity_type:
        return jsonify({"error": "entity and type required (type: ip|crypto|country|company)"}), 400

    raw = {}
    try:
        if entity_type == "ip":
            raw = _requests.get(f"http://ip-api.com/json/{entity}", timeout=8).json()
        elif entity_type == "crypto":
            resp = _requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": entity, "vs_currencies": "usd,eur,gbp", "include_24hr_change": "true", "include_market_cap": "true"},
                timeout=8,
            ).json()
            raw = {"prices": resp, "symbol": entity}
        elif entity_type == "country":
            resp = _requests.get(
                f"https://restcountries.com/v3.1/name/{entity}",
                params={"fields": "name,capital,currencies,languages,population,flags,region"},
                timeout=8,
            ).json()
            raw = resp[0] if resp else {}
        elif entity_type == "company":
            resp = _requests.get(
                "https://api.duckduckgo.com/",
                params={"q": entity, "format": "json", "no_html": 1},
                timeout=8,
            ).json()
            raw = {"abstract": resp.get("AbstractText", ""), "url": resp.get("AbstractURL", ""), "image": resp.get("Image", "")}
        else:
            return jsonify({"error": f"unknown type '{entity_type}'. Use: ip, crypto, country, company"}), 400
    except Exception as e:
        return jsonify({"error": "data_fetch_failed", "message": str(e)}), 502

    llm_result, llm_err = _call_llm(
        [{"role": "user", "content": (
            f'Synthesize this data about the {entity_type} entity "{entity}" into a structured profile. '
            f'Return JSON with: "summary" (2-3 sentence overview), "key_facts" (array of 5 bullet strings), "risk_level" (low/medium/high, if applicable), "sources" (array of source names used). '
            f'Raw data:\n{json.dumps(raw)[:2000]}'
        )}],
        system="You are a data analyst. Respond with valid JSON only — no markdown, no preamble.",
        max_tokens=512, endpoint="/enrich",
    )
    if llm_err:
        return jsonify({"error": llm_err}), 400
    profile = parse_json_from_claude(llm_result["text"]) or {}
    log_payment("/enrich", 0.05, request.remote_addr)
    return jsonify(agent_response({
        "entity": entity,
        "type": entity_type,
        "raw_data": raw,
        "profile": profile,
    }, "/enrich"))


# ── Prepaid API Key Management ─────────────────────────────────────────────────

@app.route("/auth/generate-key", methods=["POST"])
def auth_generate_key():
    data = request.get_json() or {}
    label = data.get("label", "")
    key_data = generate_key(initial_balance=0.0, label=label)
    return jsonify({
        "key": key_data["key"],
        "balance_usd": key_data["balance_usd"],
        "label": key_data["label"],
        "created_at": key_data["created_at"],
        "usage": "Add 'Authorization: Bearer <key>' to your requests. Topup via POST /auth/topup.",
        "_meta": {"free": True},
    })


@app.route("/auth/topup", methods=["POST"])
def auth_topup():
    data = request.get_json() or {}
    key = data.get("key", "")
    amount = float(data.get("amount_usd", 0))
    if not key or amount <= 0:
        return jsonify({"error": "key and amount_usd required"}), 400
    result = topup_key(key, amount)
    return jsonify(result)


@app.route("/auth/status", methods=["GET", "POST"])
def auth_status():
    key = request.args.get("key") or (request.get_json() or {}).get("key", "")
    if not key:
        return jsonify({"error": "key required"}), 400
    status = get_key_status(key)
    if not status:
        return jsonify({"error": "key_not_found"}), 404
    return jsonify(status)


@app.route("/credits/buy", methods=["POST"])
def buy_credits():
    """Buy token credits via x402. Returns a prepaid API key."""
    data = request.get_json() or {}
    amount = data.get("amount_usd", 5.0)
    label = data.get("label", "x402-credit-pack")
    key_data = generate_key(initial_balance=amount, label=label)
    return jsonify({
        "key": key_data["key"],
        "balance_usd": amount,
        "label": label,
        "pricing": "Use 'X-Pricing: metered' header for token-based billing",
    })


# ── SSE Streaming Endpoints ─────────────────────────────────────────────────────

@app.route("/stream/research", methods=["POST"])
def stream_research():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required"}), 400

    def generate():
        with claude.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system="You are a research assistant. Stream a concise research summary on the given topic.",
            messages=[{"role": "user", "content": f"Research: {topic}"}],
        ) as stream:
            for text in stream.text_stream:
                yield f"data: {json.dumps({'text': text})}\n\n"
        yield f"data: {json.dumps({'done': True, 'endpoint': '/stream/research'})}\n\n"
        log_payment("/stream/research", 0.01, request.remote_addr)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/stream/write", methods=["POST"])
def stream_write():
    data = request.get_json() or {}
    prompt = data.get("prompt", "")
    style = data.get("style", "professional")
    if not prompt:
        return jsonify({"error": "prompt required"}), 400

    def generate():
        with claude.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            system=f"You are a skilled writer. Write in a {style} style.",
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield f"data: {json.dumps({'text': text})}\n\n"
        yield f"data: {json.dumps({'done': True, 'endpoint': '/stream/write'})}\n\n"
        log_payment("/stream/write", 0.05, request.remote_addr)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/stream/analyze", methods=["POST"])
def stream_analyze():
    data = request.get_json() or {}
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "content required"}), 400

    def generate():
        with claude.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system="You are an analyst. Provide structured analysis with key findings, sentiment, and recommendations.",
            messages=[{"role": "user", "content": f"Analyze:\n\n{content[:3000]}"}],
        ) as stream:
            for text in stream.text_stream:
                yield f"data: {json.dumps({'text': text})}\n\n"
        yield f"data: {json.dumps({'done': True, 'endpoint': '/stream/analyze'})}\n\n"
        log_payment("/stream/analyze", 0.02, request.remote_addr)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Free Data Honeypots (extra) ─────────────────────────────────────────────────

@app.route("/data/joke", methods=["GET"])
def data_joke():
    cached = _cache_get("joke")
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            "https://official-joke-api.appspot.com/random_joke",
            timeout=5,
        )
        d = resp.json()
        result = {
            "setup": d.get("setup"),
            "punchline": d.get("punchline"),
            "type": d.get("type"),
            "_meta": {"free": True, "source": "official-joke-api.appspot.com"},
        }
        _cache_set("joke", result, 3600)  # 1 hr
        return jsonify(result)
    except Exception:
        return jsonify({
            "setup": "Why don't scientists trust atoms?",
            "punchline": "Because they make up everything.",
            "type": "general",
            "_meta": {"free": True, "source": "fallback"},
        })


@app.route("/data/quote", methods=["GET"])
def data_quote():
    category = request.args.get("category", "")
    cached = _cache_get("quote")
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get("https://zenquotes.io/api/random", timeout=5)
        d = resp.json()[0] if resp.ok else {}
        result = {
            "quote": d.get("q"),
            "author": d.get("a"),
            "tags": [category] if category else [],
            "_meta": {"free": True, "source": "zenquotes.io"},
        }
        _cache_set("quote", result, 3600)  # 1 hr
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "quote_fetch_failed", "message": str(e)}), 502


@app.route("/data/timezone", methods=["GET"])
def data_timezone():
    tz = request.args.get("tz", "America/New_York")
    ck = f"tz:{tz}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://worldtimeapi.org/api/timezone/{tz}",
            timeout=5,
        )
        d = resp.json()
        result = {
            "timezone": tz,
            "datetime": d.get("datetime"),
            "utc_offset": d.get("utc_offset"),
            "day_of_week": d.get("day_of_week"),
            "week_number": d.get("week_number"),
            "_meta": {"free": True, "source": "worldtimeapi.org"},
        }
        _cache_set(ck, result, 3600)  # 1 hr
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "timezone_fetch_failed", "message": str(e)}), 502


@app.route("/data/holidays", methods=["GET"])
def data_holidays():
    country = request.args.get("country", "US").upper()
    year = request.args.get("year", str(datetime.utcnow().year))
    ck = f"holidays:{country}:{year}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    try:
        resp = _requests.get(
            f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}",
            timeout=6,
        )
        holidays = resp.json()
        if isinstance(holidays, list):
            result = {
                "country": country,
                "year": year,
                "holidays": holidays[:20],
                "count": len(holidays),
                "_meta": {"free": True, "source": "date.nager.at"},
            }
            _cache_set(ck, result, 86400)  # 24 hr
            return jsonify(result)
        return jsonify({"error": "no_data", "country": country, "year": year}), 404
    except Exception as e:
        return jsonify({"error": "holidays_fetch_failed", "message": str(e)}), 502


# ── Stripe Payment Pages ───────────────────────────────────────────────────────

_BUY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Buy AiPayGent Credits</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 24px; }
  .card { background: #141414; border: 1px solid #2a2a2a; border-radius: 16px; padding: 40px; max-width: 520px; width: 100%; }
  h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 6px; }
  .sub { color: #888; font-size: 0.9rem; margin-bottom: 32px; }
  .plans { display: flex; gap: 12px; margin-bottom: 28px; }
  .plan { flex: 1; border: 2px solid #2a2a2a; border-radius: 12px; padding: 18px 14px; cursor: pointer; text-align: center; transition: all 0.15s; }
  .plan:hover, .plan.selected { border-color: #6366f1; background: #1a1a2e; }
  .plan .amount { font-size: 1.6rem; font-weight: 800; color: #fff; }
  .plan .credits { font-size: 0.8rem; color: #888; margin-top: 4px; }
  .plan .badge { display: inline-block; background: #6366f1; color: #fff; font-size: 0.7rem; padding: 2px 8px; border-radius: 20px; margin-top: 8px; }
  .field { margin-bottom: 20px; }
  label { display: block; font-size: 0.85rem; color: #888; margin-bottom: 6px; }
  input { width: 100%; background: #1e1e1e; border: 1px solid #2a2a2a; border-radius: 8px; padding: 11px 14px; color: #e8e8e8; font-size: 0.95rem; outline: none; transition: border-color 0.15s; }
  input:focus { border-color: #6366f1; }
  input::placeholder { color: #555; }
  .btn { width: 100%; background: #6366f1; color: #fff; border: none; border-radius: 10px; padding: 14px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.15s; }
  .btn:hover { background: #4f52d0; }
  .btn:disabled { background: #333; color: #666; cursor: not-allowed; }
  .info { background: #1a1a1a; border-radius: 8px; padding: 14px; font-size: 0.82rem; color: #888; margin-top: 24px; line-height: 1.6; }
  .info code { background: #2a2a2a; padding: 1px 5px; border-radius: 4px; color: #a78bfa; font-size: 0.8rem; }
  .error { color: #f87171; font-size: 0.85rem; margin-top: 10px; display: none; }
</style>
</head>
<body>
<div class="card">
  <h1>Buy API Credits</h1>
  <p class="sub">Pay once, call any endpoint. No subscriptions.</p>

  <div class="plans">
    <div class="plan" data-amount="5" onclick="selectPlan(this)">
      <div class="amount">$5</div>
      <div class="credits">~500 calls</div>
    </div>
    <div class="plan selected" data-amount="20" onclick="selectPlan(this)">
      <div class="amount">$20</div>
      <div class="credits">~2,000 calls</div>
      <div class="badge">Popular</div>
    </div>
    <div class="plan" data-amount="50" onclick="selectPlan(this)">
      <div class="amount">$50</div>
      <div class="credits">~5,000 calls</div>
      <div class="badge">Best value</div>
    </div>
  </div>

  <div class="field">
    <label>Label (optional)</label>
    <input type="text" id="label" placeholder="e.g. my-agent, production, testing" maxlength="60">
  </div>

  <div class="field">
    <label>Existing key to top up (optional)</label>
    <input type="text" id="existing_key" placeholder="apk_xxx — leave blank to generate a new key">
  </div>

  <button class="btn" id="pay-btn" onclick="checkout()">Pay with Card</button>
  <p class="error" id="err"></p>

  <div class="info">
    After payment you get an <code>apk_xxx</code> key. Use it as:<br>
    <code>Authorization: Bearer apk_xxx</code><br><br>
    Calls are deducted at the endpoint price ($0.01–$0.20). Check balance at <code>/auth/status</code>.
  </div>
</div>
<script>
let selectedAmount = 20;
function selectPlan(el) {
  document.querySelectorAll('.plan').forEach(p => p.classList.remove('selected'));
  el.classList.add('selected');
  selectedAmount = parseInt(el.dataset.amount);
}
async function checkout() {
  const btn = document.getElementById('pay-btn');
  const err = document.getElementById('err');
  btn.disabled = true; btn.textContent = 'Redirecting...'; err.style.display = 'none';
  try {
    const res = await fetch('/stripe/create-checkout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        amount: selectedAmount,
        label: document.getElementById('label').value.trim(),
        existing_key: document.getElementById('existing_key').value.trim(),
      })
    });
    const data = await res.json();
    if (data.url) { window.location.href = data.url; }
    else { err.textContent = data.error || 'Something went wrong'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Pay with Card'; }
  } catch(e) { err.textContent = 'Network error'; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Pay with Card'; }
}
</script>
</body>
</html>"""

_SUCCESS_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Payment Successful — AiPayGent</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
  .card { background: #141414; border: 1px solid #2a2a2a; border-radius: 16px; padding: 40px; max-width: 520px; width: 100%; text-align: center; }
  .icon { font-size: 3rem; margin-bottom: 16px; }
  h1 { font-size: 1.6rem; margin-bottom: 8px; }
  .sub { color: #888; margin-bottom: 28px; }
  .key-box { background: #1e1e1e; border: 1px solid #2a2a2a; border-radius: 10px; padding: 16px; margin-bottom: 24px; }
  .key-label { font-size: 0.8rem; color: #888; margin-bottom: 6px; }
  .key-val { font-family: monospace; font-size: 0.95rem; color: #a78bfa; word-break: break-all; cursor: pointer; }
  .key-val:hover { color: #c4b5fd; }
  .balance { font-size: 1.1rem; margin-bottom: 24px; }
  .balance span { color: #34d399; font-weight: 700; }
  pre { background: #1a1a1a; border-radius: 8px; padding: 14px; font-size: 0.8rem; color: #888; text-align: left; overflow-x: auto; margin-bottom: 8px; }
  .btn { display: inline-block; background: #6366f1; color: #fff; text-decoration: none; border-radius: 10px; padding: 12px 24px; font-weight: 600; margin-top: 20px; }
  .copy-hint { font-size: 0.75rem; color: #555; margin-top: 4px; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#10003;</div>
  <h1>Payment Successful</h1>
  <p class="sub">Your API key is ready.</p>

  <div class="key-box">
    <div class="key-label">YOUR API KEY</div>
    <div class="key-val" onclick="copyKey(this)" title="Click to copy">{{ key }}</div>
    <div class="copy-hint">Click to copy</div>
  </div>

  <p class="balance">Balance: <span>${{ balance }}</span></p>

  <pre>curl https://api.aipaygent.xyz/research \\
  -H "Authorization: Bearer {{ key }}" \\
  -H "Content-Type: application/json" \\
  -d '{"topic": "quantum computing"}'</pre>

  <pre># Check balance
curl "https://api.aipaygent.xyz/auth/status?key={{ key }}"</pre>

  <a href="/buy-credits" class="btn">Buy More Credits</a>
</div>
<script>
function copyKey(el) {
  navigator.clipboard.writeText(el.textContent.trim());
  const orig = el.textContent;
  el.textContent = 'Copied!';
  setTimeout(() => el.textContent = orig, 1500);
}
</script>
</body>
</html>"""


@app.route("/buy-credits", methods=["GET"])
def buy_credits_page():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured. Set STRIPE_SECRET_KEY in .env"}), 503
    return _BUY_PAGE, 200, {"Content-Type": "text/html"}


@app.route("/stripe/create-checkout", methods=["POST"])
def stripe_create_checkout():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured"}), 503
    data = request.get_json() or {}
    amount = int(data.get("amount", 20))
    if amount not in (5, 20, 50):
        return jsonify({"error": "amount must be 5, 20, or 50"}), 400
    label = str(data.get("label", ""))[:60]
    existing_key = str(data.get("existing_key", "")).strip()

    # Generate or validate key
    if existing_key and existing_key.startswith("apk_"):
        status = get_key_status(existing_key)
        if not status:
            return jsonify({"error": "key not found"}), 404
        api_key = existing_key
        action = "topup"
    else:
        new_key = generate_key(initial_balance=0.0, label=label)
        api_key = new_key["key"]
        action = "new"

    try:
        session = _stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"AiPayGent API Credits — ${amount}",
                        "description": f"Prepaid credits for api.aipaygent.xyz. ~{amount * 100} API calls.",
                    },
                    "unit_amount": amount * 100,  # cents
                },
                "quantity": 1,
            }],
            mode="payment",
            client_reference_id=api_key,
            metadata={"api_key": api_key, "amount": str(amount), "action": action, "label": label},
            success_url=f"{BASE_URL}/buy-credits/success?key={api_key}&amount={amount}",
            cancel_url=f"{BASE_URL}/buy-credits",
        )
        return jsonify({"url": session.url, "session_id": session.id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "webhook secret not set"}), 503
    try:
        event = _stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except _stripe.error.SignatureVerificationError:
        return jsonify({"error": "invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {})
        api_key = meta.get("api_key") or session.get("client_reference_id", "")
        amount = float(meta.get("amount", 0))
        if api_key and api_key.startswith("apk_") and amount > 0:
            topup_key(api_key, amount)
            log_payment("/stripe/topup", amount, session.get("customer_details", {}).get("email", "stripe"))
            # Credit referral commission if ?ref= was passed during checkout
            ref_agent = meta.get("ref_agent", "")
            if ref_agent:
                try:
                    record_conversion(ref_agent, "stripe_purchase", amount)
                except Exception:
                    pass

    return jsonify({"received": True})


@app.route("/buy-credits/success", methods=["GET"])
def buy_credits_success():
    key = request.args.get("key", "")
    amount = request.args.get("amount", "")
    status = get_key_status(key) if key else None
    balance = f"{status['balance_usd']:.2f}" if status else amount
    html = _SUCCESS_PAGE.replace("{{ key }}", key).replace("{{ balance }}", balance)
    return html, 200, {"Content-Type": "text/html"}


# ── Self-Test / Canary Endpoint ───────────────────────────────────────────────

@app.route("/self-test", methods=["GET", "POST"])
def self_test():
    """Manually trigger canary probe and return results."""
    results = run_canary()
    return jsonify(results)


@app.route("/health/history", methods=["GET"])
def health_history():
    endpoint = request.args.get("endpoint")
    limit = int(request.args.get("limit", 100))
    return jsonify({"history": get_health_history(endpoint, limit)})


# ── Cost Tracking & Visibility ────────────────────────────────────────────────

@app.route("/costs", methods=["GET"])
def costs():
    """Show today's Claude API cost and throttle status."""
    today = get_daily_cost()
    throttled = is_cost_throttled(DAILY_COST_LIMIT_USD)
    return jsonify({
        "today": today,
        "daily_limit_usd": DAILY_COST_LIMIT_USD,
        "throttled": throttled,
        "model_in_use": _get_model(),
        "_meta": {"note": "Set DAILY_COST_LIMIT_USD env var to change limit (default $10)"},
    })


# ── Agent-to-Agent Economy ────────────────────────────────────────────────────

_economy_stats = {
    "tasks_auto_posted": 0,
    "tasks_auto_completed": 0,
    "knowledge_seeded": 0,
    "last_run": None,
}

# Topics the KnowledgeAgent seeds into the knowledge base automatically
_KNOWLEDGE_SEEDS = [
    {
        "topic": "aipaygent-api-reference",
        "content": (
            "AiPayGent API (https://api.aipaygent.xyz) has 140+ endpoints. "
            "Key endpoints: /research ($0.01), /write ($0.05), /analyze ($0.02), /code ($0.05), "
            "/scrape/google-maps ($0.10), /chain ($0.25 for 5-step pipelines), /rag ($0.05). "
            "Free tier: 10 calls/day per IP. Prepaid keys: /buy-credits. "
            "OpenAPI spec: /openapi.json. MCP tools: /sdk."
        ),
        "tags": ["api", "aipaygent", "reference"],
        "entry_id": "kb-aipaygent-api-ref-v1",
    },
    {
        "topic": "x402-payment-protocol",
        "content": (
            "x402 is a payment protocol for AI agents. HTTP 402 response includes payment details. "
            "Agents pay USDC on Base Mainnet. AiPayGent wallet: 0x3E9C23822184c7E0D1f2b650bef6218a56B9EeeD."
            "Facilitator: https://x402.org/facilitator. Use x402-python or x402-js SDK."
        ),
        "tags": ["x402", "payment", "usdc", "base"],
        "entry_id": "kb-x402-protocol-v1",
    },
    {
        "topic": "ai-agent-best-practices",
        "content": (
            "Best practices for AI agents: 1) Use idempotency keys (X-Idempotency-Key header). "
            "2) Cache free data endpoints (weather=600s, crypto=120s). "
            "3) Use /chain for multi-step pipelines instead of sequential calls. "
            "4) Store agent state with /memory/set. 5) Use /task/submit to delegate work. "
            "6) Monitor costs at /costs. 7) Subscribe to tasks at /task/subscribe."
        ),
        "tags": ["agents", "best-practices", "architecture"],
        "entry_id": "kb-agent-best-practices-v1",
    },
]

# Auto-tasks that specialist agents post to the task board periodically
_AUTO_TASKS = [
    {
        "posted_by": "agent-content-v1",
        "title": "Generate tutorial blog post for trending AI topic",
        "description": "Research current trending AI topics on HN and write a developer tutorial connecting it to AiPayGent endpoints. Post result to knowledge base.",
        "skills_needed": ["writing", "research"],
        "reward_usd": 0.0,
        "key": "auto-blog-task",
    },
    {
        "posted_by": "agent-analytics-v1",
        "title": "Analyze recent API usage patterns",
        "description": "Review the /stats endpoint data and identify which endpoints are most popular, any usage spikes, and opportunities to improve the service.",
        "skills_needed": ["analyze", "data"],
        "reward_usd": 0.0,
        "key": "auto-analytics-task",
    },
]

_economy_task_keys_posted: set = set()


def _run_agent_economy():
    """
    Autonomous agent economy loop — runs every 30 minutes.
    1. KnowledgeAgent seeds the knowledge base with API docs.
    2. Specialist agents auto-post tasks to the task board.
    3. Agents auto-claim and complete open tasks using Claude.
    """
    global _economy_stats
    now = datetime.utcnow().isoformat()
    _economy_stats["last_run"] = now

    # 1. Seed knowledge base (idempotent by entry_id)
    for seed in _KNOWLEDGE_SEEDS:
        try:
            add_knowledge(
                topic=seed["topic"],
                content=seed["content"],
                author_agent="agent-knowledge-v1",
                tags=seed["tags"],
                entry_id=seed["entry_id"],
            )
            _economy_stats["knowledge_seeded"] += 1
        except Exception:
            pass

    # 2. Auto-post tasks (once per key per process lifetime to avoid spam)
    for task_def in _AUTO_TASKS:
        key = task_def["key"]
        if key not in _economy_task_keys_posted:
            try:
                # Check if an open task with this title already exists
                existing = browse_tasks(status="open", limit=50)
                titles = [t["title"] for t in existing]
                if task_def["title"] not in titles:
                    submit_task(
                        posted_by=task_def["posted_by"],
                        title=task_def["title"],
                        description=task_def["description"],
                        skills_needed=task_def["skills_needed"],
                        reward_usd=task_def["reward_usd"],
                    )
                    _economy_stats["tasks_auto_posted"] += 1
                _economy_task_keys_posted.add(key)
            except Exception:
                pass

    # 3. Auto-claim and complete open tasks that match specialist capabilities
    _auto_complete_tasks()


def _auto_complete_tasks():
    """Scan open tasks and auto-complete those matching specialist agent skills."""
    open_tasks = browse_tasks(status="open", limit=20)
    for task in open_tasks:
        skills = task.get("skills_needed", [])
        title = task["title"]
        desc = task["description"]
        task_id = task["task_id"]

        # Match to a specialist agent
        agent_id = None
        if any(s in skills for s in ["writing", "content", "social-media"]):
            agent_id = "agent-content-v1"
        elif any(s in skills for s in ["research", "web-search"]):
            agent_id = "agent-search-v1"
        elif any(s in skills for s in ["analyze", "data", "compare"]):
            agent_id = "agent-analytics-v1"
        elif any(s in skills for s in ["rag", "knowledge-base", "fact-check"]):
            agent_id = "agent-knowledge-v1"
        elif any(s in skills for s in ["sentiment", "keywords", "classify"]):
            agent_id = "agent-nlp-v1"

        if not agent_id:
            continue

        # Claim it
        claimed = claim_task(task_id, agent_id)
        if not claimed:
            continue

        # Complete it with Claude
        try:
            msg = claude.messages.create(
                model=_get_model(),
                max_tokens=800,
                messages=[{
                    "role": "user",
                    "content": f"Complete this task as {agent_id}:\n\nTitle: {title}\n\nDescription: {desc}\n\nProvide a concise, useful result."
                }]
            )
            result_text = msg.content[0].text
            # Track cost
            track_cost(f"economy/{agent_id}", msg.model, msg.usage.input_tokens, msg.usage.output_tokens)
            complete_task(task_id, agent_id, result_text)
            _economy_stats["tasks_auto_completed"] += 1

            # If result is knowledge-worthy, add it to the KB
            if any(s in skills for s in ["research", "writing", "analyze"]):
                try:
                    add_knowledge(
                        topic=title[:80],
                        content=result_text[:1000],
                        author_agent=agent_id,
                        tags=skills,
                    )
                except Exception:
                    pass
        except Exception:
            pass


@app.route("/economy/status", methods=["GET"])
def economy_status():
    """Show autonomous agent economy stats."""
    open_tasks = browse_tasks(status="open", limit=50)
    completed_tasks = browse_tasks(status="completed", limit=50)
    return jsonify({
        "stats": _economy_stats,
        "task_board": {
            "open": len(open_tasks),
            "completed": len(completed_tasks),
        },
        "knowledge_base": {
            "trending": get_trending_topics(5),
        },
        "cost_today": get_daily_cost(),
        "throttled": is_cost_throttled(DAILY_COST_LIMIT_USD),
    })


# ── RSS Feed ──────────────────────────────────────────────────────────────────

@app.route("/feed.xml", methods=["GET"])
def rss_feed():
    """RSS 2.0 feed of blog posts — enables syndication to aggregators."""
    posts = list_blog_posts()
    items_xml = ""
    import re as _re2
    for p in posts[:20]:
        pub_date = p.get("generated_at", "")[:10]
        slug = p["slug"]
        link = f"https://api.aipaygent.xyz/blog/{slug}"
        full = get_blog_post(slug)
        raw = full.get("content", "") if full else ""
        raw = _re2.sub(r'^```html\s*', '', raw)
        desc = _re2.sub(r'<[^>]+>', '', raw)[:300].strip()
        if not desc:
            desc = p.get("title", "")
        items_xml += f"""
  <item>
    <title><![CDATA[{p['title']}]]></title>
    <link>{link}</link>
    <guid isPermaLink="true">{link}</guid>
    <description><![CDATA[{desc}]]></description>
    <pubDate>{pub_date}</pubDate>
    <category>{p.get('endpoint','api')}</category>
  </item>"""

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>AiPayGent Developer Blog</title>
    <link>https://api.aipaygent.xyz/blog</link>
    <description>Developer tutorials for building AI agents with AiPayGent — 140+ Claude-powered API endpoints. First 10 calls/day free.</description>
    <language>en-us</language>
    <atom:link href="https://api.aipaygent.xyz/feed.xml" rel="self" type="application/rss+xml"/>
    <image>
      <url>https://api.aipaygent.xyz/og-image.png</url>
      <title>AiPayGent</title>
      <link>https://api.aipaygent.xyz</link>
    </image>
    {items_xml}
  </channel>
</rss>"""
    return rss, 200, {"Content-Type": "application/rss+xml; charset=utf-8"}


# ── OG Image (SVG served as PNG fallback) ─────────────────────────────────────

@app.route("/og-image.png", methods=["GET"])
def og_image():
    """Social sharing card image — returned as inline SVG (browsers + crawlers accept it)."""
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0a0a0a"/>
      <stop offset="100%" stop-color="#1e1b4b"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="60" y="60" width="1080" height="510" rx="20" fill="#141414" opacity="0.8"/>
  <text x="600" y="220" font-family="system-ui,sans-serif" font-size="72" font-weight="800" fill="#ffffff" text-anchor="middle">AiPayGent</text>
  <text x="600" y="310" font-family="system-ui,sans-serif" font-size="32" fill="#a78bfa" text-anchor="middle">Pay-per-use Claude AI API</text>
  <text x="600" y="390" font-family="system-ui,sans-serif" font-size="26" fill="#888" text-anchor="middle">140+ endpoints · 10 free calls/day · No signup</text>
  <text x="600" y="460" font-family="system-ui,sans-serif" font-size="22" fill="#6366f1" text-anchor="middle">api.aipaygent.xyz</text>
  <rect x="440" y="490" width="320" height="48" rx="24" fill="#6366f1"/>
  <text x="600" y="521" font-family="system-ui,sans-serif" font-size="20" font-weight="600" fill="#fff" text-anchor="middle">Try free — no credit card</text>
</svg>"""
    return svg, 200, {"Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=86400"}


@app.route("/favicon.svg")
def favicon_svg():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#6366f1"/>
  <text x="32" y="46" font-family="system-ui,sans-serif" font-size="36" font-weight="800" fill="#fff" text-anchor="middle">Ai</text>
</svg>"""
    return svg, 200, {"Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=604800"}


@app.route("/favicon.ico")
def favicon_ico():
    return "", 204


# ── Changelog ─────────────────────────────────────────────────────────────────

@app.route("/changelog", methods=["GET"])
def changelog():
    """Auto-generated changelog showing recent blog posts, new endpoints, and stats."""
    posts = list_blog_posts()[:5]
    post_items = "".join(
        f'<li><a href="/blog/{p["slug"]}">{p["title"]}</a> <small style="color:#888">({p.get("generated_at","")[:10]})</small></li>'
        for p in posts
    )
    # Get payment stats
    total_calls = 0
    total_earned = 0.0
    try:
        if os.path.exists(PAYMENTS_LOG):
            with open(PAYMENTS_LOG) as f:
                entries = [json.loads(l) for l in f if l.strip()]
            total_calls = len(entries)
            total_earned = sum(e.get("amount_usd", 0) for e in entries)
    except Exception:
        pass

    cost = get_daily_cost()
    health = run_canary.__module__  # just to confirm import OK

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AiPayGent Changelog</title>
<meta name="description" content="What's new at AiPayGent — latest blog posts, API updates, and service stats.">
<link rel="canonical" href="https://api.aipaygent.xyz/changelog">
<meta property="og:title" content="AiPayGent Changelog">
<meta property="og:url" content="https://api.aipaygent.xyz/changelog">
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;line-height:1.7;color:#1a1a1a}}
a{{color:#6366f1}}h1,h2{{color:#1e1b4b}}.stat{{display:inline-block;background:#f8f7ff;border:1px solid #e0e0ff;border-radius:8px;padding:10px 20px;margin:6px;text-align:center}}
.stat .n{{font-size:1.8rem;font-weight:800;color:#6366f1}}.stat .l{{font-size:0.8rem;color:#888}}</style>
</head>
<body>
<p><a href="/">← Home</a></p>
<h1>Changelog</h1>
<p>Live service status and recent updates for <a href="https://api.aipaygent.xyz">api.aipaygent.xyz</a>.</p>

<h2>Service Stats</h2>
<div>
  <div class="stat"><div class="n">{total_calls:,}</div><div class="l">Total API calls</div></div>
  <div class="stat"><div class="n">${total_earned:.2f}</div><div class="l">Revenue logged</div></div>
  <div class="stat"><div class="n">140+</div><div class="l">Endpoints</div></div>
  <div class="stat"><div class="n">10</div><div class="l">Free calls/day</div></div>
  <div class="stat"><div class="n">${cost['total_cost_usd']:.4f}</div><div class="l">Claude cost today</div></div>
</div>

<h2>Recent Blog Posts</h2>
<ul>{post_items}</ul>
<p><a href="/blog">All posts →</a> · <a href="/feed.xml">RSS →</a></p>

<h2>Recent Updates</h2>
<ul>
  <li><strong>Mar 2026</strong> — Self-sufficiency: canary monitoring, trending blog auto-generation, agent economy, per-IP rate limiting, DB self-maintenance</li>
  <li><strong>Mar 2026</strong> — SocialBot cross-promotion: AiPayGent brand posting to Twitter + LinkedIn daily</li>
  <li><strong>Mar 2026</strong> — Referral system (10% commission), discovery engine (GitHub outreach, sitemap pings)</li>
  <li><strong>Mar 2026</strong> — Async jobs, file storage, webhook relay, free data tier (14+ endpoints)</li>
  <li><strong>Mar 2026</strong> — Prepaid API keys (Stripe), SSE streaming, MCP server (79 tools)</li>
  <li><strong>Mar 2026</strong> — 140+ endpoints: AI, scraping, code execution, agent messaging, task board, knowledge base</li>
</ul>

<p style="color:#888;font-size:0.85rem">Auto-updated · <a href="https://api.aipaygent.xyz/health">Health status</a> · <a href="https://api.aipaygent.xyz/self-test">Canary test</a></p>
</body>
</html>"""
    return Response(html, content_type="text/html")


# ── IndexNow — Instant Bing/Yandex Indexing for New Pages ────────────────────

INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "aipaygent2026indexnow")

@app.route(f"/{INDEXNOW_KEY}.txt", methods=["GET"])
def indexnow_verify():
    """IndexNow key verification file — required by Bing/Yandex."""
    return INDEXNOW_KEY, 200, {"Content-Type": "text/plain"}


def ping_indexnow(urls: list):
    """Ping IndexNow to get pages indexed on Bing/Yandex immediately."""
    try:
        payload = {
            "host": "api.aipaygent.xyz",
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://api.aipaygent.xyz/{INDEXNOW_KEY}.txt",
            "urlList": urls,
        }
        _requests.post(
            "https://api.indexnow.org/indexnow",
            json=payload,
            timeout=8,
        )
    except Exception:
        pass


# ── Dev.to Cross-Posting ──────────────────────────────────────────────────────

DEVTO_API_KEY = os.getenv("DEVTO_API_KEY", "")

def crosspost_to_devto(title: str, content_html: str, slug: str, tags: list = None) -> dict:
    """
    Cross-post a blog post to dev.to via their API.
    Set DEVTO_API_KEY in .env to enable (get from dev.to/settings/extensions).
    """
    if not DEVTO_API_KEY:
        return {"skipped": "DEVTO_API_KEY not set"}
    try:
        import re as _re3
        # Convert HTML to markdown-ish for dev.to (it accepts both)
        markdown_body = _re3.sub(r'<[^>]+>', '', content_html)
        article = {
            "article": {
                "title": title,
                "published": True,
                "body_markdown": (
                    f"{markdown_body}\n\n"
                    f"---\n"
                    f"*Try it free at [api.aipaygent.xyz](https://api.aipaygent.xyz) — 10 calls/day, no credit card.*\n"
                    f"*Original post: [api.aipaygent.xyz/blog/{slug}](https://api.aipaygent.xyz/blog/{slug})*"
                ),
                "tags": (tags or ["ai", "api", "python"])[:4],
                "canonical_url": f"https://api.aipaygent.xyz/blog/{slug}",
                "series": "AiPayGent Developer Tutorials",
            }
        }
        resp = _requests.post(
            "https://dev.to/api/articles",
            json=article,
            headers={"api-key": DEVTO_API_KEY, "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {"posted": True, "url": data.get("url", ""), "id": data.get("id")}
        return {"posted": False, "status": resp.status_code, "detail": resp.text[:200]}
    except Exception as e:
        return {"posted": False, "error": str(e)}


# ── Reddit Post Generator ─────────────────────────────────────────────────────

@app.route("/reddit-posts", methods=["GET"])
def reddit_posts():
    """
    Returns ready-to-copy posts for key subreddits.
    Post these manually on launch day for max initial traffic.
    """
    posts = list_blog_posts()
    top_post = posts[0] if posts else {"title": "AiPayGent API", "slug": ""}
    subreddits = [
        {
            "subreddit": "r/MachineLearning",
            "title": "[P] AiPayGent — Pay-per-use Claude API with 140+ endpoints. Free tier (10/day), x402 crypto payments, MCP tools.",
            "body": f"""I built a pay-per-use AI API on top of Claude with 140+ endpoints — research, write, code, analyze, scrape, RAG, vision, diagrams, and more.

**Key features:**
- First 10 calls/day completely free (no signup, no key)
- Pay per call with Stripe ($5 for ~500 calls) or USDC on Base via x402
- 79 MCP tools for Claude Code/Desktop
- Agent infrastructure: messaging, task board, file storage, webhook relay, async jobs
- 14+ free real-time data endpoints (weather, crypto, news, Wikipedia, arXiv)

```bash
curl https://api.aipaygent.xyz/research \\
  -H "Content-Type: application/json" \\
  -d '{{"topic": "transformer attention mechanisms"}}'
```

API: https://api.aipaygent.xyz
OpenAPI: https://api.aipaygent.xyz/openapi.json
Blog: https://api.aipaygent.xyz/blog""",
        },
        {
            "subreddit": "r/LocalLLaMA",
            "title": "AiPayGent — Claude API with x402 micropayments. Agents can pay per call with USDC, 10 free calls/day",
            "body": f"""Built a micro-payment AI API for agent-to-agent use. Your AI agent can call it autonomously using x402 (HTTP 402 payment protocol) with USDC on Base, or just use the free tier.

**Why this is interesting for agents:**
- True pay-per-call (not subscription) — agents pay exactly what they use
- No API key management — pay with USDC or use free daily quota
- 79 MCP tools for integration with Claude Code/Desktop
- Agent task board, messaging, memory, webhook relay built in

Try it: https://api.aipaygent.xyz/preview (no auth needed)""",
        },
        {
            "subreddit": "r/selfhosted",
            "title": "I built a pay-per-use AI API (Claude-powered) that runs on a Raspberry Pi — x402 payments, 140+ endpoints",
            "body": f"""Running on a Raspberry Pi 5 at home behind Cloudflare tunnel.

Stack: Flask + Gunicorn + SQLite + APScheduler + Cloudflare tunnel + systemd

It handles x402 payment verification, API key management, referral tracking, scheduled blog generation, and 140+ Claude-powered endpoints — all on a Pi.

What surprised me: SQLite handles this fine for the traffic volume a self-hosted project gets.

Live at: https://api.aipaygent.xyz
Source architecture explained: https://api.aipaygent.xyz/blog""",
        },
        {
            "subreddit": "r/Python",
            "title": "I built a pay-per-use REST API with Flask that accepts crypto micropayments (x402) — here's how",
            "body": f"""Tutorial post: {top_post['title']}
https://api.aipaygent.xyz/blog/{top_post.get('slug', '')}

The core pattern: wrap Flask routes with x402 payment middleware. When an agent calls the endpoint without payment, it gets HTTP 402 with payment instructions. Client attaches a signed USDC transaction header, retries, and gets the result.

Full Python client example in the blog post above.""",
        },
    ]
    return jsonify({"subreddits": subreddits, "note": "Copy-paste these for launch day. Post during peak hours 9am-12pm EST."})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
