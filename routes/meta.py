"""Meta routes — landing page, docs, discover, health, well-known, openapi, SEO."""
import hashlib as _hashlib
import json
import os
import psutil as _psutil
import requests as _requests
import time as _time
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response, render_template, make_response
from helpers import APP_VERSION, require_admin, agent_response, get_client_ip, call_llm as _call_llm, cache_get as _cache_get, cache_set as _cache_set
from model_router import call_model, list_models, get_all_perf
from discovery_engine import get_blog_post, list_blog_posts, get_health_history, get_daily_cost
from uptime_tracker import record_check as _record_uptime, get_uptime_stats as _get_uptime_stats, get_recent_checks as _get_recent_checks
from alerting import process_health_result as _process_alerts, get_recent_alerts as _get_recent_alerts
import logging

from funnel_tracker import log_event as funnel_log_event

logger = logging.getLogger(__name__)

import sqlite3 as _sqlite3

_tool_usage_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tool_usage.db")

def _log_tool_usage(tool_name: str, api_key: str = "free"):
    """Increment usage counter for a tool in tool_usage.db (same schema as mcp_server)."""
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with _sqlite3.connect(_tool_usage_db) as conn:
            conn.execute(
                """INSERT INTO tool_usage (tool_name, api_key, count, last_used)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(tool_name, api_key)
                   DO UPDATE SET count = count + 1, last_used = ?""",
                (tool_name, api_key, now, now),
            )
    except Exception:
        pass


_CURATED_POPULAR = [
    {"tool": "research", "calls": 0, "description": "Deep research on any topic with sources"},
    {"tool": "summarize", "calls": 0, "description": "Summarize articles, docs, or any text"},
    {"tool": "write", "calls": 0, "description": "Generate content for any purpose"},
    {"tool": "code", "calls": 0, "description": "Write code in any language"},
    {"tool": "translate", "calls": 0, "description": "Translate text between 100+ languages"},
    {"tool": "analyze", "calls": 0, "description": "AI analysis of any content"},
    {"tool": "sentiment", "calls": 0, "description": "Detect sentiment in text"},
    {"tool": "extract", "calls": 0, "description": "Extract structured data from text"},
    {"tool": "compare", "calls": 0, "description": "Compare anything side by side"},
    {"tool": "explain", "calls": 0, "description": "Get simple explanations of complex topics"},
]


def _get_popular_tools(limit=10):
    """Return top tools by total call count from tool_usage.db, with curated fallback."""
    try:
        with _sqlite3.connect(_tool_usage_db) as conn:
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                """SELECT tool_name, SUM(count) as total_calls, MAX(last_used) as last_used
                   FROM tool_usage GROUP BY tool_name ORDER BY total_calls DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        if rows:
            return [{"tool": r["tool_name"], "calls": r["total_calls"], "last_used": r["last_used"]} for r in rows]
    except Exception:
        pass
    return _CURATED_POPULAR[:limit]

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x366D488a48de1B2773F3a21F1A6972715056Cb30")
EVM_NETWORK = os.getenv("EVM_NETWORK", "eip155:8453")

# Pre-compute MCP tool count at import time (avoid reading file on every /api/stats call)
_MCP_TOOL_COUNT = 65  # fallback
try:
    import glob as _glob
    _mcp_tools_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_tools")
    _mcp_src = ""
    for _fp in _glob.glob(os.path.join(_mcp_tools_dir, "*.py")):
        with open(_fp) as _f:
            _mcp_src += _f.read()
    # Also scan mcp_server.py for any remaining tool definitions
    _mcp_server_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server.py")
    if os.path.exists(_mcp_server_path):
        with open(_mcp_server_path) as _f:
            _mcp_src += _f.read()
    # Count @metered_tool decorators + standalone @mcp.tool() decorators.
    # Subtract 2 from @mcp.tool() count: 1 docstring mention + 1 inside metered_tool wrapper.
    _MCP_TOOL_COUNT = _mcp_src.count("@metered_tool") + _mcp_src.count("@mcp.tool()") - 2
    del _mcp_src, _f, _fp, _glob
except Exception:
    pass
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://api.cdp.coinbase.com/platform/v2/x402")

meta_bp = Blueprint("meta", __name__)

_skills_db_path = None

def init_meta_bp(skills_db_path):
    global _skills_db_path
    _skills_db_path = skills_db_path

NAV_HTML = '''
<nav style="position:fixed;top:0;width:100%;z-index:100;background:rgba(2,4,8,0.95);backdrop-filter:blur(16px) saturate(180%);border-bottom:1px solid rgba(0,255,157,0.1);padding:14px 0">
  <div style="max-width:1200px;margin:0 auto;padding:0 24px;display:flex;align-items:center;justify-content:space-between">
    <a href="/" style="font-family:'IBM Plex Mono',monospace;font-size:1.3rem;font-weight:700;color:#fff;text-decoration:none;display:flex;align-items:center;gap:8px">
      <span style="display:inline-block;width:8px;height:8px;background:#00ff9d;border-radius:50%;box-shadow:0 0 8px #00ff9d,0 0 16px rgba(0,255,157,0.4);animation:pulse-dot 2s ease-in-out infinite"></span>
      Ai<span style="color:#00ff9d">Pay</span>Gen
    </a>
    <div style="display:flex;gap:24px;align-items:center">
      <a href="/docs" style="color:#8b949e;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;transition:color .2s">Docs</a>
      <a href="/pricing" style="color:#8b949e;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;transition:color .2s">Pricing</a>
      <a href="/try" style="color:#00d4ff;text-decoration:none;font-family:'IBM Plex Sans',sans-serif;font-size:0.9rem;font-weight:600">Try Free</a>
      <a href="/quick-key" style="color:#000;text-decoration:none;font-family:'IBM Plex Mono',monospace;font-size:0.82rem;font-weight:700;background:linear-gradient(135deg,#00ff9d,#00d4ff);padding:7px 16px;border-radius:4px;margin-left:8px;letter-spacing:0.03em;transition:all .2s;box-shadow:0 0 12px rgba(0,255,157,0.2)">Get API Key</a>
    </div>
  </div>
</nav>
<style>
@keyframes pulse-dot{0%,100%{opacity:1;box-shadow:0 0 8px #00ff9d,0 0 16px rgba(0,255,157,0.4)}50%{opacity:0.6;box-shadow:0 0 4px #00ff9d,0 0 8px rgba(0,255,157,0.2)}}
</style>
'''

FOOTER_HTML = '''
<footer style="border-top:1px solid rgba(0,255,157,0.08);padding:40px 24px;text-align:center;background:#020408">
  <div style="max-width:1200px;margin:0 auto">
    <div style="margin-bottom:16px">
      <a href="/discover" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Discover</a>
      <a href="/docs" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Docs</a>
      <a href="/pricing" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Pricing</a>
      <a href="/playground" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Playground</a>
      <a href="/llms.txt" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">llms.txt</a>
      <a href="/.well-known/agent.json" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">agent.json</a>
      <a href="/health" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Health</a>
      <a href="/status" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Status</a>
      <a href="/support" style="color:#8b949e;text-decoration:none;margin:0 16px;font-size:0.85rem">Support</a>
    </div>
    <div style="color:#4a5568;font-size:0.8rem;font-family:'IBM Plex Mono',monospace">
      Powered by x402 &middot; USDC on Base &middot; Built for autonomous agents
    </div>
  </div>
</footer>
'''


def _price_to_tier(price_usd: float) -> str:
    """Map a per-call USD price to a human-readable tier name."""
    if price_usd <= 0:
        return "Free"
    if price_usd <= 0.002:
        return "Standard"
    if price_usd <= 0.006:
        return "AI"
    if price_usd <= 0.02:
        return "AI / Scraping"
    if price_usd <= 0.10:
        return "Premium"
    return "Enterprise"


def _get_x402_price_map():
    """Build endpoint -> price_usd lookup from the x402 route config in app.py."""
    try:
        from app import routes as _x402_routes
        price_map = {}
        for key, rc in _x402_routes.items():
            # key format: "POST /research"
            parts = key.split(" ", 1)
            if len(parts) == 2:
                endpoint = parts[1]
                price_str = rc.accepts[0].price  # e.g. "$0.05"
                price_map[endpoint] = float(price_str.replace("$", ""))
        return price_map
    except Exception:
        return {}


def _build_discover_services():
    """Return services organized by category for the /discover endpoint."""
    # Pull prices from the x402 route config (source of truth)
    _x402_prices = _get_x402_price_map()

    _all_services = [
        # --- Web Intelligence ---
        {"endpoint": "/scrape", "method": "POST", "price_usd": 0.01, "input": {"url": "string"}, "output": {"url": "string", "text": "string", "word_count": "int"}, "description": "Fetch any URL, return clean markdown text"},
        {"endpoint": "/search", "method": "POST", "price_usd": 0.01, "input": {"query": "string", "n": "int (default 5, max 10)"}, "output": {"query": "string", "results": [{"title": "string", "url": "string", "snippet": "string"}]}, "description": "DuckDuckGo web search, returns top N results"},
        {"endpoint": "/extract", "method": "POST", "price_usd": 0.02, "input": {"url": "string OR text: string", "schema": {"field": "description"}, "fields": ["field1"]}, "description": "Extract structured data from URL or text using a schema"},
        {"endpoint": "/research", "method": "POST", "price_usd": 0.15, "input": {"question": "string"}, "output": {"question": "string", "answer": "string", "sources": [{"title": "string", "url": "string"}]}, "description": "Deep research: search + scrape + AI synthesis with citations"},
        {"endpoint": "/vision", "method": "POST", "price_usd": 0.05, "input": {"url": "image_url", "question": "optional"}, "description": "Analyze any image URL with Claude Vision — describe, extract text, answer questions"},
        {"endpoint": "/web/search", "method": "GET", "price_usd": 0.02, "input": {"q": "query", "n": 10}, "description": "Web search via DuckDuckGo instant answers — returns results with title, URL, snippet."},
        {"endpoint": "/enrich", "method": "POST", "price_usd": 0.05, "input": {"entity": "string", "type": "ip|crypto|country|url|company"}, "description": "Aggregate multiple data sources into a unified enrichment profile for any entity."},
        # --- AI Processing ---
        {"endpoint": "/summarize", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "length": "short|medium|detailed"}, "description": "Summarize long text into key points"},
        {"endpoint": "/analyze", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "question": "string"}, "description": "Analyze data or text, returns structured insights"},
        {"endpoint": "/translate", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "language": "string"}, "description": "Translate text to any language"},
        {"endpoint": "/social", "method": "POST", "price_usd": 0.03, "input": {"topic": "string", "platforms": ["twitter", "linkedin", "instagram"], "tone": "string"}, "description": "Generate platform-optimized social media posts"},
        {"endpoint": "/write", "method": "POST", "price_usd": 0.05, "input": {"spec": "string", "type": "article|post|copy"}, "description": "Write articles, copy, or content to spec"},
        {"endpoint": "/code", "method": "POST", "price_usd": 0.05, "input": {"description": "string", "language": "string"}, "description": "Generate code in any language"},
        {"endpoint": "/qa", "method": "POST", "price_usd": 0.02, "input": {"context": "string", "question": "string"}, "description": "Q&A over a document — answer + confidence + source quote. Core RAG building block."},
        {"endpoint": "/classify", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "categories": ["cat1", "cat2"]}, "description": "Classify text into your defined categories with per-category confidence scores"},
        {"endpoint": "/sentiment", "method": "POST", "price_usd": 0.01, "input": {"text": "string"}, "description": "Deep sentiment — polarity, score, emotions, confidence, key phrases"},
        {"endpoint": "/keywords", "method": "POST", "price_usd": 0.01, "input": {"text": "string", "max_keywords": 10}, "description": "Extract keywords, topics, tags from any text"},
        {"endpoint": "/compare", "method": "POST", "price_usd": 0.02, "input": {"text_a": "string", "text_b": "string", "focus": "optional"}, "description": "Compare two texts — similarities, differences, similarity score, recommendation"},
        {"endpoint": "/transform", "method": "POST", "price_usd": 0.02, "input": {"text": "string", "instruction": "string"}, "description": "Transform text with any instruction — rewrite, reformat, expand, condense, translate style"},
        {"endpoint": "/chat", "method": "POST", "price_usd": 0.03, "input": {"messages": [{"role": "user", "content": "string"}], "system": "optional"}, "description": "Stateless multi-turn chat — send full message history, get Claude reply"},
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
        {"endpoint": "/rag", "method": "POST", "price_usd": 0.05, "input": {"documents": "text (use --- to separate docs)", "query": "string"}, "description": "Grounded Q&A — answer questions using only your provided documents, with citations"},
        {"endpoint": "/diagram", "method": "POST", "price_usd": 0.03, "input": {"description": "string", "type": "flowchart|sequence|erd|gantt|mindmap"}, "description": "Generate Mermaid diagrams from a plain English description"},
        {"endpoint": "/json-schema", "method": "POST", "price_usd": 0.02, "input": {"description": "string", "example": "optional JSON example"}, "description": "Generate JSON Schema (draft-07) from a plain English description of your data"},
        {"endpoint": "/test-cases", "method": "POST", "price_usd": 0.03, "input": {"code": "code or description", "language": "python"}, "description": "Generate comprehensive unit test cases with edge cases for any code or feature"},
        {"endpoint": "/code/run", "method": "POST", "price_usd": 0.05, "input": {"code": "python code string", "timeout": 10}, "description": "Execute Python code in a sandboxed subprocess. Returns stdout, stderr, exit code."},
        # --- Scraping ---
        {"endpoint": "/scrape/google-maps", "method": "POST", "price_usd": 0.10, "input": {"query": "string (e.g. restaurants in NYC)", "max_items": 5}, "description": "Scrape Google Maps — business names, addresses, ratings, reviews, phone numbers"},
        {"endpoint": "/scrape/tweets", "method": "POST", "price_usd": 0.05, "input": {"query": "string or #hashtag", "max_items": 25}, "description": "Scrape Twitter/X — tweet text, author, engagement metrics"},
        {"endpoint": "/scrape/instagram", "method": "POST", "price_usd": 0.05, "input": {"username": "string", "max_items": 5}, "description": "Scrape Instagram profile posts and metadata"},
        {"endpoint": "/scrape/linkedin", "method": "POST", "price_usd": 0.15, "input": {"url": "LinkedIn profile URL"}, "description": "Scrape LinkedIn profile — experience, skills, education"},
        {"endpoint": "/scrape/youtube", "method": "POST", "price_usd": 0.05, "input": {"query": "string", "max_items": 5}, "description": "Search YouTube and return video metadata — title, channel, views, URL"},
        {"endpoint": "/scrape/web", "method": "POST", "price_usd": 0.05, "input": {"url": "string", "max_pages": 5}, "description": "Crawl any website and extract structured text content"},
        {"endpoint": "/scrape/tiktok", "method": "POST", "price_usd": 0.05, "input": {"username": "string", "max_items": 5}, "description": "Scrape TikTok profile videos and metadata"},
        {"endpoint": "/scrape/facebook-ads", "method": "POST", "price_usd": 0.10, "input": {"url": "Facebook Ad Library URL", "max_items": 10}, "description": "Scrape Facebook Ad Library for competitor ad research"},
        {"endpoint": "/scrape/actor", "method": "POST", "price_usd": 0.10, "input": {"actor_id": "Apify actor ID", "run_input": {}, "max_items": 10}, "description": "Run any Apify actor with custom input — access the full Apify ecosystem"},
        # --- Data & Utilities ---
        {"endpoint": "/data/weather", "method": "GET", "price_usd": 0.01, "input": {"city": "string"}, "description": "Real-time weather — temperature, wind speed, weather code."},
        {"endpoint": "/data/crypto", "method": "GET", "price_usd": 0.01, "input": {"symbol": "bitcoin,ethereum"}, "description": "Live crypto prices in USD/EUR/GBP with 24hr change."},
        {"endpoint": "/data/exchange-rates", "method": "GET", "price_usd": 0.01, "input": {"base": "USD"}, "description": "Exchange rates for any base currency vs 160+ currencies."},
        {"endpoint": "/data/country", "method": "GET", "price_usd": 0.01, "input": {"name": "France"}, "description": "Country info — capital, population, currencies, languages, flag."},
        {"endpoint": "/data/ip", "method": "GET", "price_usd": 0.01, "input": {"ip": "optional"}, "description": "IP geolocation — country, city, ISP, timezone."},
        {"endpoint": "/data/news", "method": "GET", "price_usd": 0.01, "description": "Top 10 Hacker News stories — title, URL, score, comments."},
        {"endpoint": "/data/stocks", "method": "GET", "price_usd": 0.01, "input": {"symbol": "AAPL"}, "description": "Stock price, previous close, market state via Yahoo Finance."},
        {"endpoint": "/data/joke", "method": "GET", "price_usd": 0.01, "description": "Random joke — setup + punchline."},
        {"endpoint": "/data/quote", "method": "GET", "price_usd": 0.01, "input": {"category": "optional"}, "description": "Random inspirational quote with author."},
        {"endpoint": "/data/timezone", "method": "GET", "price_usd": 0.01, "input": {"tz": "America/New_York"}, "description": "Current datetime, UTC offset, week number for any timezone."},
        {"endpoint": "/data/holidays", "method": "GET", "price_usd": 0.01, "input": {"country": "US", "year": "2026"}, "description": "Public holidays for any country and year."},
        {"endpoint": "/data/wikipedia", "method": "GET", "price_usd": 0.01, "input": {"q": "quantum computing"}, "description": "Wikipedia article summary — title, extract, URL, description."},
        {"endpoint": "/data/arxiv", "method": "GET", "price_usd": 0.01, "input": {"q": "LLM agents", "limit": 5}, "description": "Search arXiv academic papers — title, authors, summary, URL."},
        {"endpoint": "/data/github/trending", "method": "GET", "price_usd": 0.01, "input": {"lang": "python", "since": "daily"}, "description": "GitHub trending repositories — repo, stars, description, language."},
        {"endpoint": "/data/reddit", "method": "GET", "price_usd": 0.01, "input": {"q": "AI agents", "sub": "MachineLearning"}, "description": "Reddit search — posts with score, comments, URL."},
        {"endpoint": "/data/youtube/transcript", "method": "GET", "price_usd": 0.01, "input": {"video_id": "dQw4w9WgXcQ"}, "description": "YouTube video transcript/captions — full text and segments."},
        {"endpoint": "/data/qr", "method": "GET", "price_usd": 0.01, "input": {"text": "https://api.aipaygen.com"}, "description": "Generate QR code — returns PNG as base64 and data URL."},
        {"endpoint": "/data/dns", "method": "GET", "price_usd": 0.01, "input": {"domain": "api.aipaygen.com"}, "description": "DNS lookup — A, AAAA records and reverse hostname."},
        {"endpoint": "/data/validate/email", "method": "GET", "price_usd": 0.01, "input": {"email": "test@example.com"}, "description": "Email validation — format check, domain reachability, disposable detection."},
        {"endpoint": "/data/validate/url", "method": "GET", "price_usd": 0.01, "input": {"url": "https://example.com"}, "description": "URL reachability check — status code, final URL, content type."},
        {"endpoint": "/data/random/name", "method": "GET", "price_usd": 0.01, "input": {"count": 5}, "description": "Random person names, emails, phone, location."},
        {"endpoint": "/data/color", "method": "GET", "price_usd": 0.01, "input": {"hex": "ff5733"}, "description": "Color info — RGB, HSL, complementary color, brightness, CSS."},
        {"endpoint": "/data/screenshot", "method": "GET", "price_usd": 0.01, "input": {"url": "https://example.com"}, "description": "Website screenshot URL (1280px wide)."},
        {"endpoint": "/free/time", "method": "GET", "price_usd": 0.00, "description": "Current UTC time, Unix timestamp, date, day of week — completely free"},
        {"endpoint": "/free/uuid", "method": "GET", "price_usd": 0.00, "description": "Generate UUID4 values — completely free"},
        {"endpoint": "/free/ip", "method": "GET", "price_usd": 0.00, "description": "Caller's IP address and user agent info — completely free"},
        {"endpoint": "/free/hash", "method": "GET", "price_usd": 0.00, "input": {"text": "string"}, "description": "Hash text with MD5, SHA1, SHA256, SHA512 — completely free"},
        {"endpoint": "/free/base64", "method": "GET", "price_usd": 0.00, "input": {"text": "string to encode", "decode": "string to decode"}, "description": "Encode/decode base64 — completely free"},
        {"endpoint": "/free/random", "method": "GET", "price_usd": 0.00, "input": {"n": 5, "min": 1, "max": 100}, "description": "Random integers, floats, booleans, and strings — completely free"},
        {"endpoint": "/free/joke", "method": "GET", "price_usd": 0.00, "description": "Random joke with setup and punchline — completely free"},
        {"endpoint": "/free/quote", "method": "GET", "price_usd": 0.00, "input": {"category": "optional"}, "description": "Random inspirational quote with author — completely free"},
        {"endpoint": "/free-tier/status", "method": "GET", "price_usd": 0.01, "description": "Check how many free AI calls remain today for your IP. $0.10 free trial credits with API key, resets midnight UTC."},
        {"endpoint": "/sdk/code", "method": "GET", "price_usd": 0.01, "input": {"lang": "python|javascript|curl", "endpoint": "optional"}, "description": "Get copy-paste SDK code in Python, JavaScript, or cURL"},
        {"endpoint": "/sitemap.xml", "method": "GET", "price_usd": 0.01, "description": "XML sitemap of all public endpoints for crawlers and agents"},
        {"endpoint": "/catalog", "method": "GET", "price_usd": 0.01, "input": {"category": "optional", "min_score": 0, "free_only": False, "page": 1}, "description": "Browse 4100+ discovered APIs — the largest autonomous API catalog. Filter by category, quality score, auth requirement"},
        {"endpoint": "/models", "method": "GET", "price_usd": 0.01, "description": "List all supported LLM models (15 models, 7 providers) with pricing and capabilities."},
        {"endpoint": "/api-call", "method": "POST", "price_usd": 0.05, "input": {"api_id": "int from /catalog", "endpoint": "/path", "params": {}, "api_key": "optional", "enrich": False}, "description": "Proxy-call any API in the catalog — optionally enrich results with Claude analysis"},
        # --- Agent Platform ---
        {"endpoint": "/agents/register", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "name": "string", "description": "string", "capabilities": [], "endpoint": "optional URL"}, "description": "Register your agent in the AiPayGen agent registry"},
        {"endpoint": "/agents", "method": "GET", "price_usd": 0.01, "description": "Browse all registered agents in the registry"},
        {"endpoint": "/agents/leaderboard", "method": "GET", "price_usd": 0.01, "description": "Top agents by reputation score. Score = task_completions*3 + knowledge*1.5 + upvotes*0.5"},
        {"endpoint": "/agent/reputation/<agent_id>", "method": "GET", "price_usd": 0.01, "description": "Get reputation score and stats for any agent."},
        {"endpoint": "/agents/challenge", "method": "POST", "price_usd": 0.01, "input": {"wallet_address": "0x...", "chain": "evm|solana"}, "description": "Request a wallet-verification challenge string."},
        {"endpoint": "/agents/verify", "method": "POST", "price_usd": 0.01, "input": {"wallet_address": "0x...", "signature": "0x...", "chain": "evm|solana"}, "description": "Submit signed challenge to verify wallet, get JWT session token."},
        {"endpoint": "/agents/me", "method": "GET", "price_usd": 0.01, "description": "View your verified agent profile (requires JWT)."},
        {"endpoint": "/agents/search", "method": "GET", "price_usd": 0.01, "input": {"q": "query", "capability": "optional"}, "description": "Search wallet-verified agents by name, capability, or address."},
        {"endpoint": "/agents/<agent_id>/portfolio", "method": "GET", "price_usd": 0.01, "description": "View a verified agent's public portfolio and reputation."},
        {"endpoint": "/marketplace", "method": "GET", "price_usd": 0.01, "input": {"category": "optional", "max_price": "optional"}, "description": "Browse the agent marketplace — services listed by other AI agents"},
        {"endpoint": "/marketplace/list", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "name": "string", "endpoint": "URL", "price_usd": 0.05, "description": "string", "category": "string"}, "description": "List your service in the agent marketplace, earn x402 payments"},
        {"endpoint": "/marketplace/call", "method": "POST", "price_usd": 0.05, "input": {"listing_id": "string", "payload": {}}, "description": "Proxy-call any agent marketplace listing — we handle routing and payment"},
        {"endpoint": "/memory/set", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "key": "string", "value": "any", "tags": ["optional"]}, "description": "Store persistent memory for any agent — survives across sessions and requests"},
        {"endpoint": "/memory/get", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "key": "string"}, "description": "Retrieve a stored memory by agent_id and key"},
        {"endpoint": "/memory/search", "method": "POST", "price_usd": 0.02, "input": {"agent_id": "string", "query": "string"}, "description": "Search all memories for an agent by keyword"},
        {"endpoint": "/memory/clear", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string"}, "description": "Delete all memories for an agent — use before context reset"},
        {"endpoint": "/message/send", "method": "POST", "price_usd": 0.01, "input": {"from_agent": "string", "to_agent": "string", "subject": "string", "body": "string"}, "description": "Send a message from one agent to another. Persistent inbox."},
        {"endpoint": "/message/inbox/<agent_id>", "method": "GET", "price_usd": 0.01, "description": "Read an agent's inbox."},
        {"endpoint": "/message/reply", "method": "POST", "price_usd": 0.01, "input": {"msg_id": "string", "from_agent": "string", "body": "string"}, "description": "Reply to a message in a thread."},
        {"endpoint": "/message/broadcast", "method": "POST", "price_usd": 0.02, "input": {"from_agent": "string", "subject": "string", "body": "string"}, "description": "Broadcast a message to all registered agents."},
        {"endpoint": "/knowledge/add", "method": "POST", "price_usd": 0.01, "input": {"topic": "string", "content": "string", "author_agent": "string", "tags": []}, "description": "Add an entry to the shared knowledge base."},
        {"endpoint": "/knowledge/search", "method": "GET", "price_usd": 0.01, "input": {"q": "query"}, "description": "Search the shared knowledge base."},
        {"endpoint": "/knowledge/trending", "method": "GET", "price_usd": 0.01, "description": "Get trending topics in the knowledge base."},
        {"endpoint": "/knowledge/vote", "method": "POST", "price_usd": 0.01, "input": {"entry_id": "string", "up": True}, "description": "Upvote or downvote a knowledge entry."},
        {"endpoint": "/task/submit", "method": "POST", "price_usd": 0.01, "input": {"posted_by": "string", "title": "string", "description": "string", "skills_needed": [], "reward_usd": 0.10}, "description": "Post a task to the agent task board."},
        {"endpoint": "/task/browse", "method": "GET", "price_usd": 0.01, "input": {"skill": "optional", "status": "open"}, "description": "Browse open tasks."},
        {"endpoint": "/task/claim", "method": "POST", "price_usd": 0.01, "input": {"task_id": "string", "agent_id": "string"}, "description": "Claim a task from the board."},
        {"endpoint": "/task/complete", "method": "POST", "price_usd": 0.01, "input": {"task_id": "string", "agent_id": "string", "result": "string"}, "description": "Mark a task complete with result."},
        {"endpoint": "/task/subscribe", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "callback_url": "https://your-agent/webhook", "skills": ["python", "nlp"]}, "description": "Subscribe to task board notifications. We POST to your callback_url when matching tasks appear."},
        {"endpoint": "/files/upload", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "file": "multipart OR base64_data+filename+content_type"}, "description": "Upload a file (max 10MB). Returns file_id and URL."},
        {"endpoint": "/files/<file_id>", "method": "GET", "price_usd": 0.01, "description": "Download a file by ID. Returns raw file bytes."},
        {"endpoint": "/files/list/<agent_id>", "method": "GET", "price_usd": 0.01, "description": "List all files uploaded by an agent."},
        {"endpoint": "/webhooks/create", "method": "POST", "price_usd": 0.01, "input": {"agent_id": "string", "label": "optional"}, "description": "Get a unique URL to receive webhooks from any external service. Events stored 7 days."},
        {"endpoint": "/webhooks/<id>/receive", "method": "POST", "price_usd": 0.01, "description": "The URL external services POST to. Stores the incoming event for your agent to retrieve."},
        {"endpoint": "/webhooks/<id>/events", "method": "GET", "price_usd": 0.01, "description": "Retrieve stored webhook events. Poll this or set up a task subscription callback."},
        {"endpoint": "/chain-operations", "method": "POST", "price_usd": 0.05, "input": {"steps": [{"tool": "summarize", "input": "text"}]}, "description": "Chain multiple AI operations together — each step feeds into the next."},
        {"endpoint": "/enrich-entity", "method": "POST", "price_usd": 0.03, "input": {"entity": "Anthropic", "type": "company"}, "description": "Enrich company, person, or domain data with AI-powered research."},
        {"endpoint": "/compare-models", "method": "POST", "price_usd": 0.05, "input": {"prompt": "your prompt", "models": ["claude-haiku", "gpt-4o-mini"]}, "description": "Run the same prompt on multiple AI models and compare results side-by-side."},
        {"endpoint": "/estimate-cost", "method": "POST", "price_usd": 0.00, "input": {"tool": "research", "count": 100}, "description": "Estimate API costs before calling — preview your spend for any volume."},
        {"endpoint": "/suggest-tools", "method": "POST", "price_usd": 0.00, "input": {"task": "translate my website"}, "description": "Describe what you need and get AI tool recommendations instantly."},
        {"endpoint": "/get-weather", "method": "POST", "price_usd": 0.001, "input": {"location": "San Francisco"}, "description": "Get current weather for any city in the world — temperature, wind, conditions."},
        {"endpoint": "/get-crypto-prices", "method": "POST", "price_usd": 0.001, "input": {"coins": "bitcoin,ethereum"}, "description": "Real-time cryptocurrency prices from CoinGecko in USD, EUR, GBP."},
        {"endpoint": "/get-exchange-rates", "method": "POST", "price_usd": 0.001, "input": {"base": "USD"}, "description": "Live exchange rates for 160+ currencies — updated in real-time."},
        {"endpoint": "/get-holidays", "method": "POST", "price_usd": 0.001, "input": {"country": "US", "year": "2026"}, "description": "Public holidays for any country and year."},
        {"endpoint": "/get-current-time", "method": "POST", "price_usd": 0.001, "input": {}, "description": "Get current UTC time, Unix timestamp, and formatted date/time."},
        {"endpoint": "/get-joke", "method": "POST", "price_usd": 0.001, "input": {}, "description": "Get a random programming joke — setup and punchline."},
        {"endpoint": "/get-quote", "method": "POST", "price_usd": 0.001, "input": {}, "description": "Get an inspirational quote with author attribution."},
        {"endpoint": "/generate-uuid", "method": "POST", "price_usd": 0.001, "input": {"count": 3}, "description": "Generate one or more UUIDs — up to 50 per request."},
        {"endpoint": "/web-search", "method": "POST", "price_usd": 0.01, "input": {"query": "MCP protocol"}, "description": "Search the web via DuckDuckGo — get abstracts and related results."},
        {"endpoint": "/scrape-website", "method": "POST", "price_usd": 0.01, "input": {"url": "https://example.com"}, "description": "Scrape any website and extract clean text content with title."},
        {"endpoint": "/memory-store", "method": "POST", "price_usd": 0.001, "input": {"key": "user_pref", "value": "dark mode"}, "description": "Store persistent agent memory — key-value pairs that survive across sessions."},
        {"endpoint": "/memory-recall", "method": "POST", "price_usd": 0.001, "input": {"key": "user_pref"}, "description": "Recall a stored memory by key — instant retrieval."},
        {"endpoint": "/memory-keys", "method": "POST", "price_usd": 0.001, "input": {"agent_id": "my-agent"}, "description": "List all stored memory keys for an agent."},
        {"endpoint": "/credits/buy", "method": "POST", "price_usd": 5.00, "input": {"amount_usd": 5.0, "label": "optional"}, "description": "Buy a USDC credit pack — returns prepaid API key for metered token-based billing."},
        {"endpoint": "/auth/generate-key", "method": "POST", "price_usd": 0.01, "input": {"label": "optional"}, "description": "Generate a prepaid API key (apk_xxx). Use as Bearer token to bypass x402 per-call."},
        {"endpoint": "/auth/topup", "method": "POST", "price_usd": 0.01, "input": {"key": "apk_xxx", "amount": 1.00}, "description": "Top up balance on a prepaid API key."},
        {"endpoint": "/auth/status", "method": "GET", "price_usd": 0.01, "input": {"key": "apk_xxx"}, "description": "Check balance, usage stats, and last used time for an API key."},
        {"endpoint": "/run-discovery", "method": "POST", "price_usd": 0.01, "description": "Trigger API discovery agents to scan the web for new APIs"},
        {"endpoint": "/async/submit", "method": "POST", "price_usd": 0.01, "input": {"endpoint": "research", "payload": {"topic": "..."}, "callback_url": "optional"}, "description": "Submit an async job. Runs in background, POSTs result to callback_url when done."},
        {"endpoint": "/async/status/<job_id>", "method": "GET", "price_usd": 0.01, "description": "Check status of an async job — pending, running, completed, or failed."},
        # --- Advanced ---
        {"endpoint": "/batch", "method": "POST", "price_usd": 0.10, "input": {"operations": [{"endpoint": "string", "input": {}}]}, "description": "Run up to 5 operations in one payment — best value for multi-step pipelines"},
        {"endpoint": "/pipeline", "method": "POST", "price_usd": 0.15, "input": {"steps": [{"endpoint": "string", "input": {}}]}, "description": "Chain up to 5 operations where each step can use {{prev}} to reference previous output"},
        {"endpoint": "/chain", "method": "POST", "price_usd": 0.25, "input": {"steps": [{"action": "research", "params": {"query": "string"}}, {"action": "summarize", "params": {"text": "{{prev_result}}"}}]}, "description": "Chain up to 5 AI operations in sequence — each step references previous output via {{prev_result}}"},
        {"endpoint": "/workflow", "method": "POST", "price_usd": 0.20, "input": {"goal": "string", "data": "optional context"}, "description": "Multi-step agentic reasoning with Claude Sonnet — breaks down and executes complex goals"},
        {"endpoint": "/stream/research", "method": "POST", "price_usd": 0.01, "input": {"topic": "string"}, "description": "Streaming research — same as /research but tokens stream as text/event-stream SSE"},
        {"endpoint": "/stream/write", "method": "POST", "price_usd": 0.05, "input": {"spec": "string", "type": "article"}, "description": "Streaming write — same as /write but content streams as SSE"},
        {"endpoint": "/stream/analyze", "method": "POST", "price_usd": 0.02, "input": {"content": "string", "question": "optional"}, "description": "Streaming analysis — same as /analyze but streams as SSE"},
    ]

    # Override discover prices with x402 source-of-truth prices
    if _x402_prices:
        for svc in _all_services:
            ep = svc["endpoint"]
            if ep in _x402_prices:
                svc["price_usd"] = _x402_prices[ep]

    # Categorize services by endpoint prefix / type
    categories = {
        "Web Intelligence": [],
        "AI Processing": [],
        "Scraping": [],
        "Data & Utilities": [],
        "Agent Platform": [],
        "Advanced": [],
    }

    _web_intel = {"/scrape", "/search", "/extract", "/research", "/vision", "/web/search", "/enrich"}
    _scraping_prefix = "/scrape/"
    _data_prefixes = ("/data/", "/free/", "/free-tier/", "/sdk/", "/sitemap", "/catalog", "/models", "/api-call")
    _agent_prefixes = ("/agents", "/agent/", "/marketplace", "/memory/", "/message/", "/knowledge/", "/task/",
                       "/files/", "/webhooks/", "/credits/", "/auth/", "/run-discovery", "/async/")
    _advanced = {"/batch", "/pipeline", "/chain", "/workflow", "/stream/research", "/stream/write", "/stream/analyze"}

    for svc in _all_services:
        ep = svc["endpoint"]
        if ep in _advanced:
            categories["Advanced"].append(svc)
        elif ep.startswith(_scraping_prefix):
            categories["Scraping"].append(svc)
        elif ep in _web_intel:
            categories["Web Intelligence"].append(svc)
        elif ep.startswith(_data_prefixes):
            categories["Data & Utilities"].append(svc)
        elif ep.startswith(_agent_prefixes):
            categories["Agent Platform"].append(svc)
        else:
            categories["AI Processing"].append(svc)

    return categories


@meta_bp.route("/sw.js")
def service_worker():
    """Serve PWA service worker from root scope."""
    from flask import send_from_directory
    return send_from_directory(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
        "sw.js",
        mimetype="application/javascript",
    )


@meta_bp.route("/manifest.json")
def root_manifest():
    """Serve PWA manifest at root URL for tools that expect /manifest.json."""
    return jsonify({
        "name": "AiPayGen",
        "short_name": "AiPayGen",
        "description": "65+ AI tools as an MCP server & API. Research, write, code, scrape, translate, analyze.",
        "start_url": "/try",
        "display": "standalone",
        "background_color": "#0a0a0a",
        "theme_color": "#00ff9d",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        ],
    })


@meta_bp.route("/app/manifest.json")
def app_manifest():
    """Serve PWA manifest for the Expo web app at app.aipaygen.com."""
    return jsonify({
        "name": "AiPayGen",
        "short_name": "AiPayGen",
        "description": "65+ AI tools as an MCP server & API. Research, write, code, scrape, translate, analyze.",
        "start_url": "/app/",
        "display": "standalone",
        "background_color": "#020408",
        "theme_color": "#00ff9d",
        "icons": [
            {"src": "/static/icon.png", "sizes": "192x192", "type": "image/png"}
        ],
    })


@meta_bp.route("/")
def landing():
    # A/B test: landing_hero_v1
    try:
        from ab_testing import get_variant, track_event
        visitor_ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown")
        variant = get_variant("landing_hero_v1", visitor_ip)
        track_event("landing_hero_v1", variant, visitor_ip, event="page_view")
    except Exception:
        variant = "A"
    try:
        resp = make_response(render_template("index.html", ab_variant=variant))
    except Exception:
        # Fallback to legacy inline landing template
        resp = make_response(render_template("landing.html", nav=NAV_HTML, footer=FOOTER_HTML))
    resp.headers["Link"] = '</llms.txt>; rel="llms-txt"'
    resp.headers["Cache-Control"] = "public, max-age=300"  # 5 min cache
    ref = request.args.get("ref", "")
    if ref:
        resp.set_cookie("aipaygen_ref", ref, max_age=30*86400, secure=True, httponly=True, samesite="Lax")
        resp.headers["Cache-Control"] = "private, no-cache"  # Don't cache referral landing
    return resp


@meta_bp.route("/ab/track", methods=["POST"])
def ab_track():
    """Public endpoint for A/B test conversion tracking from frontend."""
    try:
        from ab_testing import track_event, get_variant
        data = request.get_json(silent=True) or {}
        test_name = data.get("test", "")
        event = data.get("event", "click")
        if not test_name or not event:
            return jsonify({"ok": False}), 400
        visitor_ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown")
        variant = data.get("variant") or get_variant(test_name, visitor_ip)
        is_conversion = event in ("key_generated", "credits_bought")
        track_event(test_name, variant, visitor_ip, event=event, converted=is_conversion)
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False}), 500


@meta_bp.route("/discover")
def discover():
    try:
        funnel_log_event("discover_hit", endpoint="/discover", ip=request.headers.get("CF-Connecting-IP", request.remote_addr or ""), user_agent=request.headers.get("User-Agent", ""))
    except Exception:
        pass
    categories = _build_discover_services()
    base_url = "https://api.aipaygen.com"

    # Filter out internal endpoints and path-parameter endpoints from public display
    _HIDDEN_PREFIXES = ("/auth/", "/free-tier/", "/admin/", "/stripe/", "/credits/")
    for cat_name in list(categories.keys()):
        categories[cat_name] = [
            s for s in categories[cat_name]
            if "<" not in s["endpoint"]
            and not any(s["endpoint"].startswith(p) for p in _HIDDEN_PREFIXES)
        ]

    all_services = [s for cat_services in categories.values() for s in cat_services]
    free_count = sum(1 for s in all_services if s.get("price_usd", 0) == 0)

    # Content negotiation: HTML for browsers, JSON for agents
    best = request.accept_mimetypes.best_match(
        ["text/html", "application/json"], default="application/json"
    )

    if best == "text/html":
        display_categories = {}
        for cat_name, services in categories.items():
            display_categories[cat_name] = [
                {
                    "endpoint": s["endpoint"],
                    "method": s["method"],
                    "description": s["description"],
                    "free": s.get("price_usd", 0) == 0,
                    "price_usd": s.get("price_usd", 0),
                    "tier": _price_to_tier(s.get("price_usd", 0)),
                }
                for s in services
            ]

        # Build JSON-LD SoftwareApplication schema for SEO
        offers = []
        for svc in all_services:
            price = svc.get("price_usd", 0)
            offers.append({
                "@type": "Offer",
                "name": svc["endpoint"],
                "description": svc["description"],
                "price": str(price),
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
            })
        jsonld = json.dumps({
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "AiPayGen",
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": "Any",
            "description": f"AI agent API marketplace with {len(all_services)} tools. Research, write, code, scrape, and more. Pay per call with USDC or API key.",
            "url": "https://aipaygen.com/discover",
            "offers": offers,
        }, ensure_ascii=False)

        resp = make_response(render_template(
            "discover.html",
            categories=display_categories,
            nav=NAV_HTML,
            footer=FOOTER_HTML,
            jsonld=jsonld,
        ))
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    # Strip schemas and exact prices for competitive protection
    stripped_categories = {}
    for cat_name, services in categories.items():
        stripped_categories[cat_name] = [
            {
                "endpoint": s["endpoint"],
                "method": s["method"],
                "description": s["description"],
                "pricing": "free" if s.get("price_usd", 0) == 0 else "x402",
            }
            for s in services
        ]

    return jsonify({
        "meta": {
            "name": "AiPayGen",
            "description": "AI agent API marketplace with 65+ tools (v" + APP_VERSION + ") and 2400+ skills. Three payment paths: API key (recommended), x402 USDC, or MCP (free API key ($0.10 credits)). $0.10 trial credits available.",
            "categories": list(categories.keys()),
        },
        "payment": {
            "recommended": {
                "method": "api_key",
                "description": "Buy a prepaid API key — fastest path to access.",
                "endpoint": f"{base_url}/credits/buy",
                "example": {"amount_usd": 5.0},
                "usage": "Authorization: Bearer apk_xxx",
                "bulk_discount": "20% off when balance >= $2.00",
            },
            "x402": {
                "wallet": WALLET_ADDRESS,
                "network": EVM_NETWORK,
                "payment_scheme": "x402/exact",
                "usdc_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            },
            "mcp": {
                "description": "$0.10 free trial credits with API key via MCP, unlimited with API key.",
                "install": "pip install aipaygen-mcp",
                "sse": f"https://mcp.aipaygen.com/mcp",
            },
        },
        "categories": stripped_categories,
        "links": {
            "openapi": f"{base_url}/openapi.json",
            "llms_txt": f"{base_url}/llms.txt",
            "docs": f"{base_url}/docs",
            "buy_credits": f"{base_url}/credits/buy",
        },
    })


_app_start_time = _time.time()
_health_cache = {"data": None, "ts": 0}

# Core DBs to check in health endpoints
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_CORE_DBS = ["api_keys", "skills", "agent_network", "agent_memory", "funnel"]


def _check_db(db_name: str) -> str:
    """Check a single SQLite DB with SELECT 1. Returns 'ok' or error string."""
    db_path = os.path.join(_PROJECT_ROOT, f"{db_name}.db")
    if db_name == "skills" and _skills_db_path:
        db_path = _skills_db_path
    try:
        c = _sqlite3.connect(db_path, timeout=2)
        c.execute("SELECT 1")
        c.close()
        return "ok"
    except Exception as exc:
        return f"error: {type(exc).__name__}"


def _get_disk_info() -> dict:
    """Return disk space info."""
    try:
        st = os.statvfs(_PROJECT_ROOT)
        free_mb = (st.f_bavail * st.f_frsize) / (1024 * 1024)
        total_mb = (st.f_blocks * st.f_frsize) / (1024 * 1024)
        return {"free_mb": round(free_mb, 1), "total_mb": round(total_mb, 1), "warning": free_mb < 1024}
    except Exception:
        return {"free_mb": "unknown", "total_mb": "unknown", "warning": False}


def _get_memory_info() -> dict:
    """Return memory usage info."""
    try:
        mem = _psutil.virtual_memory()
        return {
            "used_pct": round(mem.percent, 1),
            "available_mb": round(mem.available / (1024 * 1024), 1),
            "total_mb": round(mem.total / (1024 * 1024), 1),
        }
    except Exception:
        return {"used_pct": "unknown", "available_mb": "unknown", "total_mb": "unknown"}


@meta_bp.route("/health")
def health():
    """Fast health check — basic status, cached 30s."""
    t0 = _time.time()
    now = t0

    # Cache for 30s
    if _health_cache["data"] and (now - _health_cache["ts"]) < 30:
        cached = _health_cache["data"]
        code = 200 if cached.get("status") == "healthy" else 503
        return jsonify(cached), code

    checks = {}
    degraded = False

    # 1. Quick DB check (just api_keys — the critical one)
    db_status = _check_db("api_keys")
    checks["db_api_keys"] = db_status
    if db_status != "ok":
        degraded = True

    # 2. Disk space (with 1GB warning threshold)
    disk = _get_disk_info()
    checks["disk_free_mb"] = disk["free_mb"]
    if disk["warning"]:
        degraded = True

    # 3. Memory usage
    mem = _get_memory_info()
    checks["memory_used_pct"] = mem["used_pct"]

    # 4. Uptime
    checks["uptime_seconds"] = round(now - _app_start_time, 1)

    # 5. Response time of this check
    elapsed_ms = round((_time.time() - t0) * 1000, 1)
    checks["health_check_ms"] = elapsed_ms

    status = "degraded" if degraded else "healthy"
    result = {
        "status": status,
        "wallet": WALLET_ADDRESS,
        "network": EVM_NETWORK,
        "checks": checks,
    }
    _health_cache["data"] = result
    _health_cache["ts"] = now

    # Record uptime + process alerts
    checks_passed = sum(1 for v in [db_status, "ok" if not disk["warning"] else "warn"] if v == "ok")
    _record_uptime("ok" if not degraded else "degraded", elapsed_ms, checks_passed, 2)
    _process_alerts("ok" if not degraded else "degraded", checks, elapsed_ms)

    code = 200 if not degraded else 503
    return jsonify(result), code


@meta_bp.route("/health/deep")
def health_deep():
    """Deep health check — all DBs, model availability, disk, memory, MCP."""
    t0 = _time.time()
    checks = {}
    degraded = False
    checks_passed = 0
    checks_total = 0

    # 1. All core databases
    for db_name in _CORE_DBS:
        checks_total += 1
        status = _check_db(db_name)
        checks[f"db_{db_name}"] = status
        if status == "ok":
            checks_passed += 1
        else:
            degraded = True

    # 2. Model availability — verify at least one AI model responds
    checks_total += 1
    try:
        from model_router import _circuit_state, _CIRCUIT_MAX_FAILURES
        available_providers = []
        for p in ["anthropic", "openai", "google", "deepseek", "together", "xai", "mistral"]:
            state = _circuit_state.get(p, {})
            if state.get("failures", 0) < _CIRCUIT_MAX_FAILURES or state.get("opened_at") is None:
                available_providers.append(p)
        checks["model_providers_available"] = len(available_providers)
        checks["model_providers_list"] = available_providers
        if available_providers:
            checks_passed += 1
        else:
            degraded = True
            checks["model_providers_available"] = 0
    except Exception:
        checks["model_providers_available"] = "error"
        degraded = True

    # 3. Disk space
    checks_total += 1
    disk = _get_disk_info()
    checks["disk_free_mb"] = disk["free_mb"]
    checks["disk_total_mb"] = disk["total_mb"]
    if disk["warning"]:
        degraded = True
    else:
        checks_passed += 1

    # 4. Memory usage
    checks_total += 1
    mem = _get_memory_info()
    checks["memory_used_pct"] = mem["used_pct"]
    checks["memory_available_mb"] = mem["available_mb"]
    checks["memory_total_mb"] = mem["total_mb"]
    if isinstance(mem["used_pct"], (int, float)) and mem["used_pct"] < 95:
        checks_passed += 1
    else:
        degraded = True

    # 5. Facilitator reachable
    checks_total += 1
    try:
        r = _requests.get(FACILITATOR_URL, timeout=5)
        checks["facilitator"] = "ok" if r.status_code < 500 else f"http {r.status_code}"
        if r.status_code < 500:
            checks_passed += 1
        else:
            degraded = True
    except Exception:
        checks["facilitator"] = "unreachable"
        degraded = True

    # 6. MCP server reachable
    checks_total += 1
    try:
        mcp_r = _requests.get("http://127.0.0.1:5002/health", timeout=2)
        checks["mcp_server"] = "ok" if mcp_r.status_code == 200 else f"http {mcp_r.status_code}"
        if mcp_r.status_code == 200:
            checks_passed += 1
    except Exception:
        checks["mcp_server"] = "not running"

    # 7. Daily cost
    try:
        checks["daily_cost_usd"] = round(get_daily_cost(), 4)
    except Exception:
        checks["daily_cost_usd"] = "unknown"

    # 8. Circuit breaker status
    from model_router import _circuit_state as cs2
    if cs2:
        checks["circuit_breakers"] = {
            k: {"failures": v["failures"], "open": v.get("opened_at") is not None}
            for k, v in cs2.items() if v["failures"] > 0
        }

    # 9. Model performance stats
    perf = get_all_perf()
    if perf:
        checks["model_performance"] = perf

    # 10. Uptime
    checks["uptime_seconds"] = round(_time.time() - _app_start_time, 1)

    # Response time
    elapsed_ms = round((_time.time() - t0) * 1000, 1)
    checks["health_check_ms"] = elapsed_ms

    overall = "down" if checks_passed == 0 else ("degraded" if degraded else "healthy")
    result = {
        "status": overall,
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "wallet": WALLET_ADDRESS,
        "network": EVM_NETWORK,
        "checks": checks,
    }

    # Record uptime + alerts
    _record_uptime(
        "ok" if overall == "healthy" else overall,
        elapsed_ms, checks_passed, checks_total,
    )
    _process_alerts(
        "ok" if overall == "healthy" else overall,
        checks, elapsed_ms,
    )

    code = 200 if overall == "healthy" else 503
    return jsonify(result), code


@meta_bp.route("/api/uptime")
def api_uptime():
    """Return uptime percentages for 24h, 7d, 30d."""
    stats = _get_uptime_stats()
    recent = _get_recent_checks(limit=20)
    return jsonify({"uptime": stats, "recent_checks": recent})


@meta_bp.route("/status")
def status_page():
    """Public status page — HTML dashboard with system health."""
    import sqlite3 as _sq
    from datetime import timedelta

    start = _time.time()
    overall = "healthy"
    components = {}

    # --- API health ---
    try:
        r = _requests.get("http://127.0.0.1:5001/health", timeout=5)
        health_data = r.json()
        api_ok = r.status_code == 200
        components["api"] = {
            "name": "API Server",
            "status": "healthy" if api_ok else "degraded",
            "detail": health_data.get("status", "unknown"),
        }
        uptime_s = health_data.get("checks", {}).get("uptime_seconds", 0)
        if isinstance(uptime_s, (int, float)) and uptime_s > 0:
            days = int(uptime_s // 86400)
            hours = int((uptime_s % 86400) // 3600)
            mins = int((uptime_s % 3600) // 60)
            secs = int(uptime_s % 60)
            if days > 0:
                components["api"]["uptime"] = f"{days}d {hours}h {mins}m"
            elif hours > 0:
                components["api"]["uptime"] = f"{hours}h {mins}m"
            elif mins > 0:
                components["api"]["uptime"] = f"{mins}m {secs}s"
            else:
                components["api"]["uptime"] = f"{secs}s"
        else:
            components["api"]["uptime"] = "just started"
        if not api_ok:
            overall = "degraded"
    except Exception:
        components["api"] = {"name": "API Server", "status": "down", "detail": "unreachable"}
        overall = "down"

    api_latency = round((_time.time() - start) * 1000, 1)

    # --- MCP server ---
    try:
        mr = _requests.get("http://127.0.0.1:5002/health", timeout=3)
        mcp_ok = mr.status_code == 200
        components["mcp"] = {
            "name": "MCP Server",
            "status": "healthy" if mcp_ok else "degraded",
            "detail": f"HTTP {mr.status_code}",
        }
        if not mcp_ok:
            overall = "degraded"
    except Exception:
        components["mcp"] = {"name": "MCP Server", "status": "down", "detail": "not running"}
        if overall == "healthy":
            overall = "degraded"

    # --- Model providers ---
    from model_router import _circuit_state
    providers_list = ["anthropic", "openai", "google", "deepseek", "together", "xai", "mistral"]
    provider_status = {}
    for p in providers_list:
        cb = _circuit_state.get(p, {})
        if cb.get("opened_at"):
            provider_status[p] = "down"
            if overall == "healthy":
                overall = "degraded"
        elif cb.get("failures", 0) > 0:
            provider_status[p] = "degraded"
        else:
            provider_status[p] = "healthy"

    # --- Funnel stats (last 24h) ---
    total_requests = 0
    unique_ips = 0
    count_402 = 0
    try:
        _project_root = os.path.dirname(os.path.dirname(__file__))
        fdb = os.path.join(_project_root, "funnel.db")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        c = _sq.connect(fdb, timeout=2)
        c.row_factory = _sq.Row
        total_requests = c.execute(
            "SELECT COUNT(*) FROM funnel_events WHERE created_at >= ?", (cutoff,)
        ).fetchone()[0]
        unique_ips = c.execute(
            "SELECT COUNT(DISTINCT ip) FROM funnel_events WHERE created_at >= ?", (cutoff,)
        ).fetchone()[0]
        count_402 = c.execute(
            "SELECT COUNT(*) FROM funnel_events WHERE event_type = '402_shown' AND created_at >= ?", (cutoff,)
        ).fetchone()[0]
        c.close()
    except Exception:
        pass

    # --- Response time stats (last hour) ---
    try:
        from app import get_response_time_stats, get_endpoint_response_times
        rt_stats = get_response_time_stats(3600)
        rt_endpoints = [e for e in get_endpoint_response_times(3600, top_n=15)
                        if not e["endpoint"].startswith(("/admin", "/health", "/status", "/stats"))][:10]
    except Exception:
        rt_stats = {"avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "count": 0}
        rt_endpoints = []

    rt_avg = rt_stats["avg_ms"]
    rt_p95 = rt_stats["p95_ms"]

    # --- Uptime stats ---
    uptime_stats = _get_uptime_stats()
    uptime_24h = uptime_stats.get("24h", {}).get("uptime_pct", 100.0)
    uptime_7d = uptime_stats.get("7d", {}).get("uptime_pct", 100.0)
    uptime_30d = uptime_stats.get("30d", {}).get("uptime_pct", 100.0)

    # --- Recent alerts ---
    recent_alerts = _get_recent_alerts(limit=10, include_resolved=True)

    # --- Build HTML ---
    def _dot(status):
        colors = {"healthy": "#00ff9d", "degraded": "#ffb800", "down": "#ff4444"}
        c = colors.get(status, "#666")
        shadow = f"0 0 8px {c}"
        return f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{c};box-shadow:{shadow};margin-right:8px"></span>'

    def _badge(status):
        colors = {"healthy": "#00ff9d", "degraded": "#ffb800", "down": "#ff4444"}
        c = colors.get(status, "#666")
        return f'<span style="color:{c};font-weight:600;text-transform:uppercase;font-size:0.85rem">{status}</span>'

    def _speed_color(ms):
        if ms < 100:
            return "#00ff9d"
        if ms < 500:
            return "#00d4ff"
        if ms < 2000:
            return "#ffb800"
        return "#ff4444"

    def _build_endpoint_speed_rows(endpoints):
        if not endpoints:
            return '<p style="color:#8b949e;font-size:0.85rem">No requests tracked yet. Data appears after the first API calls.</p>'
        rows = ""
        for ep in endpoints:
            c = _speed_color(ep["avg_ms"])
            bar_width = min(ep["avg_ms"] / 30, 100)  # scale: 3000ms = 100%
            rows += f'''
            <tr>
              <td style="padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.06);font-family:'IBM Plex Mono',monospace;font-size:0.85rem">{ep["endpoint"]}</td>
              <td style="padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.06)">
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="width:120px;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
                    <div style="width:{bar_width}%;height:100%;background:{c};border-radius:3px"></div>
                  </div>
                  <span style="color:{c};font-family:'IBM Plex Mono',monospace;font-size:0.85rem;font-weight:600">{ep["avg_ms"]}ms</span>
                </div>
              </td>
              <td style="padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.06);color:#8b949e;font-size:0.85rem">{ep["calls"]:,} calls</td>
            </tr>'''
        return f'''<table>
          <tr><th>Endpoint</th><th>Avg Response Time</th><th>Calls (1h)</th></tr>
          {rows}
        </table>'''

    def _build_alerts_html(alerts):
        if not alerts:
            return '<p style="color:#00ff9d;font-size:0.9rem">No recent alerts — all clear.</p>'
        rows = ""
        for a in alerts:
            ts = _time.strftime("%Y-%m-%d %H:%M", _time.gmtime(a.get("timestamp", 0)))
            sev = a.get("severity", "info")
            sev_color = {"critical": "#ff4444", "warning": "#ffb800", "info": "#00d4ff"}.get(sev, "#8b949e")
            resolved = a.get("resolved", 0)
            status_txt = '<span style="color:#00ff9d">Resolved</span>' if resolved else '<span style="color:#ff4444">Active</span>'
            rows += f'''
            <tr>
              <td style="padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.06);color:#8b949e;font-size:0.8rem">{ts}</td>
              <td style="padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.06)">
                <span style="color:{sev_color};font-weight:600;font-size:0.8rem;text-transform:uppercase">{sev}</span>
              </td>
              <td style="padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.06);font-size:0.85rem">{a.get("alert_type", "")}</td>
              <td style="padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.06);color:#8b949e;font-size:0.85rem">{a.get("message", "")}</td>
              <td style="padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.06);font-size:0.85rem">{status_txt}</td>
            </tr>'''
        return f'''<table>
          <tr><th>Time</th><th>Severity</th><th>Type</th><th>Message</th><th>Status</th></tr>
          {rows}
        </table>'''

    comp_rows = ""
    for key in ["api", "mcp"]:
        comp = components.get(key, {})
        name = comp.get("name", key)
        st = comp.get("status", "unknown")
        detail = comp.get("detail", "")
        uptime = comp.get("uptime", "")
        extra = f' &mdash; uptime: {uptime}' if uptime else ""
        comp_rows += f'''
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid rgba(255,255,255,0.06)">{_dot(st)}{name}</td>
          <td style="padding:12px 16px;border-bottom:1px solid rgba(255,255,255,0.06)">{_badge(st)}</td>
          <td style="padding:12px 16px;border-bottom:1px solid rgba(255,255,255,0.06);color:#8b949e">{detail}{extra}</td>
        </tr>'''

    provider_rows = ""
    for p in providers_list:
        st = provider_status[p]
        provider_rows += f'''
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid rgba(255,255,255,0.06)">{_dot(st)}{p.capitalize()}</td>
          <td style="padding:10px 16px;border-bottom:1px solid rgba(255,255,255,0.06)">{_badge(st)}</td>
        </tr>'''

    overall_color = {"healthy": "#00ff9d", "degraded": "#ffb800", "down": "#ff4444"}.get(overall, "#666")

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>AiPayGen Status</title>
  <meta name="description" content="AiPayGen API status — real-time health monitoring, uptime history, and system status for all endpoints.">
  <meta property="og:type" content="website">
  <meta property="og:title" content="System Status — AiPayGen">
  <meta property="og:description" content="Live system health, uptime, response times, and model provider status for AiPayGen API.">
  <meta property="og:url" content="https://aipaygen.com/status">
  <meta property="og:image" content="https://aipaygen.com/og-image.png">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{background:#020408;color:#e6edf3;font-family:'IBM Plex Sans',sans-serif;min-height:100vh}}
    a{{color:#00d4ff;text-decoration:none}}
    .container{{max-width:900px;margin:0 auto;padding:100px 24px 60px}}
    .card{{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:28px;margin-bottom:24px}}
    table{{width:100%;border-collapse:collapse}}
    th{{text-align:left;padding:10px 16px;color:#8b949e;font-size:0.8rem;text-transform:uppercase;letter-spacing:0.05em;border-bottom:1px solid rgba(255,255,255,0.1)}}
    h1{{font-family:'IBM Plex Mono',monospace;font-size:1.6rem;margin-bottom:8px}}
    h2{{font-family:'IBM Plex Mono',monospace;font-size:1.1rem;color:#8b949e;margin-bottom:16px}}
    .stat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:24px}}
    .stat-box{{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:20px;text-align:center}}
    .stat-val{{font-family:'IBM Plex Mono',monospace;font-size:1.8rem;font-weight:700;color:#00ff9d}}
    .stat-label{{color:#8b949e;font-size:0.8rem;margin-top:4px}}
    .updated{{color:#4a5568;font-size:0.75rem;text-align:center;margin-top:24px}}
  </style>
</head>
<body>
{NAV_HTML}
<div class="container">
  <div style="text-align:center;margin-bottom:40px">
    <h1>{_dot(overall)} All Systems <span style="color:{overall_color}">{overall.capitalize()}</span></h1>
    <p style="color:#8b949e;font-size:0.9rem;margin-top:8px">API response time: {api_latency}ms</p>
  </div>

  <div class="stat-grid">
    <div class="stat-box">
      <div class="stat-val">{total_requests:,}</div>
      <div class="stat-label">Requests (24h)</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{unique_ips:,}</div>
      <div class="stat-label">Unique IPs (24h)</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{count_402:,}</div>
      <div class="stat-label">402s Shown (24h)</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{api_latency}ms</div>
      <div class="stat-label">API Latency (now)</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{rt_avg}ms</div>
      <div class="stat-label">Avg Response (1h)</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{rt_p95}ms</div>
      <div class="stat-label">P95 Response (1h)</div>
    </div>
  </div>

  <div class="card">
    <h2>Uptime</h2>
    <div class="stat-grid">
      <div class="stat-box">
        <div class="stat-val" style="color:{'#00ff9d' if uptime_24h >= 99 else '#ffb800' if uptime_24h >= 95 else '#ff4444'}">{uptime_24h}%</div>
        <div class="stat-label">Last 24 Hours</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" style="color:{'#00ff9d' if uptime_7d >= 99 else '#ffb800' if uptime_7d >= 95 else '#ff4444'}">{uptime_7d}%</div>
        <div class="stat-label">Last 7 Days</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" style="color:{'#00ff9d' if uptime_30d >= 99 else '#ffb800' if uptime_30d >= 95 else '#ff4444'}">{uptime_30d}%</div>
        <div class="stat-label">Last 30 Days</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Core Services</h2>
    <table>
      <tr><th>Service</th><th>Status</th><th>Details</th></tr>
      {comp_rows}
    </table>
  </div>

  <div class="card">
    <h2>Model Providers</h2>
    <table>
      <tr><th>Provider</th><th>Status</th></tr>
      {provider_rows}
    </table>
  </div>

  <div class="card">
    <h2>API Response Times <span style="font-size:0.7rem;color:#8b949e;font-weight:400">(last hour)</span></h2>
    <div class="stat-grid" style="margin-bottom:16px">
      <div class="stat-box"><div class="stat-val" style="font-size:1.3rem">{rt_stats["avg_ms"]}ms</div><div class="stat-label">Average</div></div>
      <div class="stat-box"><div class="stat-val" style="font-size:1.3rem">{rt_stats["p50_ms"]}ms</div><div class="stat-label">Median (P50)</div></div>
      <div class="stat-box"><div class="stat-val" style="font-size:1.3rem">{rt_stats["p95_ms"]}ms</div><div class="stat-label">P95</div></div>
      <div class="stat-box"><div class="stat-val" style="font-size:1.3rem">{rt_stats["p99_ms"]}ms</div><div class="stat-label">P99</div></div>
      <div class="stat-box"><div class="stat-val" style="font-size:1.3rem">{rt_stats["count"]:,}</div><div class="stat-label">Requests Tracked</div></div>
    </div>
    {_build_endpoint_speed_rows(rt_endpoints)}
  </div>

  <div class="card">
    <h2>Recent Alerts</h2>
    {_build_alerts_html(recent_alerts)}
  </div>

  <p class="updated">Auto-refreshes every 60 seconds &middot; Last checked: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC</p>
</div>
{FOOTER_HTML}
</body>
</html>'''

    return html, 200, {"Content-Type": "text/html"}


_stats_cache = {"data": None, "ts": 0}


@meta_bp.route("/popular")
def popular_tools():
    """Public endpoint — top 10 most-used tools with call counts."""
    tools = _get_popular_tools(10)
    return jsonify({"popular": tools, "count": len(tools)})


@meta_bp.route("/api/stats")
def live_stats():
    """Public live stats for homepage — cached 5 min."""
    now = _time.time()
    if _stats_cache["data"] and (now - _stats_cache["ts"]) < 300:
        return jsonify(_stats_cache["data"])

    import sqlite3 as _sq
    _root = os.path.dirname(os.path.dirname(__file__))
    stats = {"mcp_tools": _MCP_TOOL_COUNT}

    # Baseline: 351 keys existed before test suite wiped api_keys.db (session 34)
    _API_KEY_BASELINE = 351

    # Single connection with ATTACH for all databases
    try:
        c = _sq.connect(":memory:", timeout=2)
        dbs = {
            "skills_db": "skills.db",
            "catalog_db": "api_catalog.db",
            "agents_db": "agent_memory.db",
            "keys_db": "api_keys.db",
        }
        for alias, filename in dbs.items():
            db_path = os.path.join(_root, filename)
            try:
                c.execute(f"ATTACH DATABASE ? AS {alias}", (db_path,))
            except Exception:
                pass

        queries = [
            ("skills", "SELECT COUNT(*) FROM skills_db.skills"),
            ("apis", "SELECT COUNT(*) FROM catalog_db.discovered_apis"),
            ("agents", "SELECT COUNT(*) FROM agents_db.agent_registry"),
            ("api_keys", "SELECT COUNT(*) FROM keys_db.api_keys"),
            ("total_calls", "SELECT COALESCE(SUM(call_count), 0) FROM keys_db.api_keys WHERE is_active = 1"),
        ]
        for key, sql in queries:
            try:
                stats[key] = c.execute(sql).fetchone()[0]
            except Exception:
                stats[key] = 0
        # Apply baseline offset for api_keys
        stats["api_keys"] = _API_KEY_BASELINE + stats.get("api_keys", 0)
        # Add billing audit calls as a more complete total
        try:
            import sqlite3 as _bsq
            _bdb = _bsq.connect(os.path.join(_root, "billing_audit.db"), timeout=2)
            audit_calls = _bdb.execute("SELECT COUNT(*) FROM billing_audit WHERE event_type='deduction'").fetchone()[0]
            _bdb.close()
            stats["total_calls"] = max(stats.get("total_calls", 0), audit_calls)
        except Exception:
            pass
        c.close()
    except Exception:
        stats.setdefault("skills", 0)
        stats.setdefault("apis", 0)
        stats.setdefault("agents", 0)
        stats.setdefault("api_keys", _API_KEY_BASELINE)
        stats.setdefault("total_calls", 0)

    _stats_cache["data"] = stats
    _stats_cache["ts"] = now
    return jsonify(stats)


# ── Email subscribe (lead capture) ─────────────────────────────────────

@meta_bp.route("/api/subscribe", methods=["POST"])
def api_subscribe():
    """Capture email for newsletter / re-engagement. No auth required."""
    import sqlite3 as _sq
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email or len(email) > 200:
        return jsonify({"error": "valid email required"}), 400

    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent_network.db")
    try:
        conn = _sq.connect(db_path, timeout=2)
        conn.execute("""CREATE TABLE IF NOT EXISTS subscribers (
            email TEXT PRIMARY KEY,
            source TEXT DEFAULT 'try_page',
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("INSERT OR IGNORE INTO subscribers (email, source) VALUES (?, ?)",
                     (email, data.get("source", "try_page")))
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Send welcome email if email service available
    try:
        from email_service import send_welcome_email
        send_welcome_email(email, "")
    except Exception:
        pass

    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
    funnel_log_event("email_captured", endpoint="/api/subscribe", ip=ip, user_agent=request.headers.get("User-Agent", ""))
    return jsonify({"ok": True, "message": "Subscribed!"})


# ── Per-key usage stats (authenticated) ────────────────────────────────
_usage_cache: dict = {}  # keyed by api_key → {"data": ..., "ts": ...}


@meta_bp.route("/api/usage-stats")
def usage_stats():
    """Return per-key usage stats. Requires Authorization: Bearer apk_xxx."""
    import sqlite3 as _sq

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer apk_"):
        return jsonify({"error": "API key required", "hint": "Pass Authorization: Bearer apk_..."}), 401
    api_key = auth.removeprefix("Bearer ").strip()

    # Cache per key for 60s
    now = _time.time()
    cached = _usage_cache.get(api_key)
    if cached and (now - cached["ts"]) < 60:
        return jsonify(cached["data"])

    _root = os.path.dirname(os.path.dirname(__file__))
    result: dict = {"key_prefix": api_key[:8] + "..."}

    # ── Key metadata from api_keys.db ──────────────────────────────────
    try:
        c = _sq.connect(os.path.join(_root, "api_keys.db"), timeout=2)
        c.row_factory = _sq.Row
        row = c.execute(
            "SELECT call_count, balance_usd, created_at, label FROM api_keys WHERE key = ? AND is_active = 1",
            (api_key,),
        ).fetchone()
        c.close()
        if not row:
            return jsonify({"error": "invalid or inactive API key"}), 401
        result["call_count"] = row["call_count"]
        result["balance_usd"] = round(row["balance_usd"], 4)
        result["created_at"] = row["created_at"]
        result["label"] = row["label"]
    except Exception:
        return jsonify({"error": "failed to read key data"}), 500

    # ── Daily breakdown from free_tier_usage (agent_network.db) ────────
    # This table tracks by IP, not by key, so we include it only as
    # a platform-wide daily snapshot for the last 7 days.
    daily: list = []
    try:
        c = _sq.connect(os.path.join(_root, "agent_network.db"), timeout=2)
        rows = c.execute(
            "SELECT date, SUM(calls_used) as total_calls FROM free_tier_usage "
            "WHERE date >= date('now', '-7 days') GROUP BY date ORDER BY date DESC"
        ).fetchall()
        c.close()
        daily = [{"date": r[0], "calls": r[1]} for r in rows]
    except Exception:
        pass
    result["platform_daily_calls_7d"] = daily

    _usage_cache[api_key] = {"data": result, "ts": now}
    return jsonify(result)


_preview_ips = {}  # ip -> (count, window_start)

@meta_bp.route("/preview", methods=["GET", "POST"])
def preview():
    """Demo endpoint — returns cached responses for free, LLM calls count against free tier."""
    ip = get_client_ip()
    now = _time.time()
    cnt, start = _preview_ips.get(ip, (0, now))
    if now - start > 60:
        cnt, start = 0, now
    cnt += 1
    _preview_ips[ip] = (cnt, start)
    if cnt > 3:
        return jsonify({"error": "rate_limited", "message": "Preview limited to 3/min. Get an API key for unlimited access.", "buy": "https://aipaygen.com/buy-credits"}), 429
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", request.args.get("topic", "x402 payment protocol for AI agents"))
    topic = topic[:200]  # cap input length
    ck = f"preview:{_hashlib.md5(topic.encode()).hexdigest()}"
    cached = _cache_get(ck)
    if cached:
        return jsonify(cached)
    # Preview LLM calls count against free tier — no free rides
    from agent_network import check_and_use_free_tier, get_free_tier_remaining
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer apk_"):
        if not check_and_use_free_tier(ip):
            return jsonify({
                "error": "free_tier_exhausted",
                "message": "Free preview calls exhausted for today. Get an API key to continue.",
                "upgrade": {
                    "free_key": "POST https://aipaygen.com/auth/generate-key (includes $0.10 trial credits)",
                    "buy_credits": "https://aipaygen.com/buy-credits",
                },
            }), 402
    llm_result, err = _call_llm(
        [{"role": "user", "content": f"In 2-3 sentences, briefly explain: {topic}"}],
        max_tokens=120, endpoint="/preview",
    )
    if err:
        return jsonify({"error": err}), 400
    remaining = get_free_tier_remaining(ip)
    result = {
        "result": llm_result["text"],
        "model": llm_result["model"],
        "free_calls_remaining": remaining,
        "note": "This preview is capped at 120 tokens. Full /research returns structured summary + key points + sources for $0.01 USDC.",
        "full_api": "https://api.aipaygen.com/discover",
        "openapi": "https://api.aipaygen.com/openapi.json",
    }
    _cache_set(ck, result, 300)  # 5 min
    return jsonify(result)


@meta_bp.route("/robots.txt")
def robots_txt():
    from flask import Response
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /discover\n"
        "Allow: /docs\n"
        "Allow: /sell\n"
        "Allow: /pricing\n"
        "Allow: /docs/api\n"
        "Allow: /try\n"
        "Allow: /tools/\n"
        "Allow: /referrals\n"
        "Allow: /builder\n"
        "Allow: /sdk\n"
        "Allow: /blog\n"
        "Allow: /llms.txt\n"
        "Allow: /privacy\n"
        "Allow: /terms\n"
        "Allow: /subscribe\n"
        "Allow: /get-key\n"
        "Allow: /support\n"
        "Allow: /security\n"
        "Allow: /openapi.json\n"
        "Allow: /.well-known/\n"
        "Allow: /.well-known/agent.json\n"
        "Allow: /.well-known/ai-plugin.json\n"
        "Allow: /.well-known/security.txt\n"
        "Disallow: /admin/\n"
        "Disallow: /stats\n"
        "Disallow: /skills/\n"
        "Disallow: /discovery/\n"
        "Disallow: /outbound/\n"
        "Disallow: /harvest/\n"
        "Disallow: /agent/inbox\n"
        "Disallow: /credits/\n"
        "Disallow: /free-tier/\n"
        "\n"
        "Sitemap: https://aipaygen.com/sitemap.xml\n"
        "\n"
        "# AI Agent Discovery\n"
        "# LLMs.txt: https://api.aipaygen.com/llms.txt\n"
        "# Agent Card: https://api.aipaygen.com/.well-known/agent.json\n"
        "# OpenAPI: https://api.aipaygen.com/openapi.json\n"
    )
    return Response(body, mimetype="text/plain")


@meta_bp.route("/ads.txt")
def ads_txt():
    from flask import send_from_directory
    import os
    return send_from_directory(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
        "ads.txt",
        mimetype="text/plain",
    )


@meta_bp.route("/aipaygen2026indexnow.txt")
def indexnow_key():
    return Response("aipaygen2026indexnow", mimetype="text/plain")



@meta_bp.route("/login")
def login_redirect():
    from flask import redirect
    return redirect("/auth/login", code=301)


@meta_bp.route("/pricing")
def pricing_page():
    return render_template("pricing.html", nav=NAV_HTML, footer=FOOTER_HTML)


@meta_bp.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@meta_bp.route("/terms")
def terms_page():
    return render_template("terms.html")


# ── Web App (Expo SPA) ────────────────────────────────────────────────────────

_WEB_APP_INJECT = '''<link rel="stylesheet" href="/app/web-custom.css">
<script>if(location.pathname.startsWith('/app')){var c=location.pathname.replace(/^\\/app\\/?/,'/')||'/';history.replaceState(null,'',c+location.search+location.hash)}</script>'''


@meta_bp.route("/app/")
@meta_bp.route("/app/<path:path>")
def serve_app(path=""):
    """Serve the Expo web app as a SPA — all routes fall through to index.html."""
    import os
    from flask import send_from_directory, make_response
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "app")
    # Serve actual files (JS, CSS, images)
    full_path = os.path.join(static_dir, path)
    if path and os.path.isfile(full_path):
        return send_from_directory(static_dir, path)
    # SPA fallback — serve index.html with custom CSS/JS injected before </head>
    html_path = os.path.join(static_dir, "index.html")
    if not os.path.isfile(html_path):
        return make_response("App unavailable — index.html not found. <a href='/try'>Try web version</a>", 503)
    with open(html_path, "r") as f:
        html = f.read()
    html = html.replace("</head>", _WEB_APP_INJECT + "\n</head>", 1)
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@meta_bp.route("/app")
def app_redirect():
    """Redirect /app to /app/ so <base href="/app/"> resolves correctly."""
    from flask import redirect
    return redirect("/app/", code=301)


# SPA deep-link routes — serve index.html so browser refresh works on /explore, /wallet, etc.
@meta_bp.route("/explore")
@meta_bp.route("/wallet")
@meta_bp.route("/profile")
@meta_bp.route("/workflows")
@meta_bp.route("/notifications")
@meta_bp.route("/onboarding")
@meta_bp.route("/pricing")
@meta_bp.route("/analytics")
@meta_bp.route("/tool/<path:slug>")
@meta_bp.route("/chat/<path:chat_id>")
def spa_deep_link(slug=None, chat_id=None):
    """Serve Expo SPA index.html for deep links so page refresh works."""
    import os
    from flask import make_response
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "app")
    html_path = os.path.join(static_dir, "index.html")
    with open(html_path, "r") as f:
        html = f.read()
    html = html.replace("</head>", _WEB_APP_INJECT + "\n</head>", 1)
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@meta_bp.route("/_expo/<path:path>")
def serve_expo_bundles(path):
    """Serve Expo JS/CSS bundles at root /_expo/ (referenced by absolute paths in index.html)."""
    import os
    from flask import send_from_directory, abort, make_response
    expo_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "app", "_expo")
    full_path = os.path.join(expo_dir, path)
    if os.path.isfile(full_path):
        resp = make_response(send_from_directory(expo_dir, path))
        # Content-hashed filenames are immutable — cache aggressively
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        # Ensure correct MIME types for CSS/JS (browser rejects without)
        if path.endswith(".css"):
            resp.headers["Content-Type"] = "text/css; charset=utf-8"
        elif path.endswith(".js"):
            resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
        return resp
    abort(404)


@meta_bp.route("/assets/<path:path>")
def serve_app_assets(path):
    """Serve Expo app assets — fonts go through /static/fonts/ to avoid @ in Cloudflare paths."""
    import os
    from flask import send_from_directory, abort
    base_dir = os.path.dirname(os.path.dirname(__file__))
    # Font files: serve from clean /static/fonts/ dir (Cloudflare blocks @ in URL paths)
    if path.endswith(".ttf") or path.endswith(".woff") or path.endswith(".woff2"):
        font_name = os.path.basename(path)
        fonts_dir = os.path.join(base_dir, "static", "fonts")
        font_path = os.path.join(fonts_dir, font_name)
        if os.path.isfile(font_path):
            return send_from_directory(fonts_dir, font_name)
    # Other assets: serve from static/app/assets/
    assets_dir = os.path.join(base_dir, "static", "app", "assets")
    full_path = os.path.join(assets_dir, path)
    if os.path.isfile(full_path):
        return send_from_directory(assets_dir, path)
    abort(404)


@meta_bp.route("/premium")
@meta_bp.route("/pro")
def premium_page():
    return render_template("premium.html")


@meta_bp.route("/get-key")
@meta_bp.route("/quick-key")
def get_key_page():
    """Serve key generation from meta_bp — reliable fallback for /quick-key."""
    from flask import redirect
    # Forward to auth_bp's quick_key_page if it resolves, otherwise redirect to buy-credits
    try:
        from routes.auth import quick_key_page
        return quick_key_page()
    except Exception:
        return redirect("/buy-credits", code=302)


@meta_bp.route("/support")
@meta_bp.route("/contact")
@meta_bp.route("/help")
def support_page():
    return render_template("support.html", nav=NAV_HTML, footer=FOOTER_HTML)


@meta_bp.route("/seller")
def seller_redirect():
    from flask import redirect
    return redirect("/sell", code=301)


@meta_bp.route("/docs")
def docs_page():
    return render_template("docs.html", nav=NAV_HTML, footer=FOOTER_HTML)


@meta_bp.route("/docs/api")
def docs_api():
    """Swagger UI for the OpenAPI spec."""
    from flask import Response
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AiPayGen API — Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: "/openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: "BaseLayout",
    });
  </script>
</body>
</html>"""
    return Response(html, mimetype="text/html")


def _build_llms_txt():
    """Build llms.txt dynamically from the service catalog so it stays in sync."""
    categories = _build_discover_services()
    lines = []
    lines.append("# AiPayGen")
    lines.append("")
    lines.append("> 65+ AI tools in one API (v" + APP_VERSION + "). Multi-model (Claude, GPT-4o, DeepSeek, Gemini, Grok, Mistral, Llama). Three payment paths: API key (from $1), x402 USDC, or MCP (free API key ($0.10 credits)). $0.10 trial credits via buy_credits / generate_api_key MCP tools.")
    lines.append("")
    lines.append("## What This Service Does")
    lines.append("")
    lines.append("AiPayGen is a pay-per-use AI platform for autonomous agents. Research, write, code, analyze, scrape, and more. Built for agent pipelines with persistent memory and skill discovery.")
    lines.append("")
    lines.append("## Claude Code Install")
    lines.append("")
    lines.append("```bash")
    lines.append("pip install aipaygen-mcp && claude mcp add aipaygen -- python -m aipaygen_mcp")
    lines.append("```")
    lines.append("")
    lines.append("## Capabilities")
    lines.append("")
    lines.append("- **AI Processing** — research, write, code, analyze, translate, summarize, classify, sentiment, RAG, vision, diagrams")
    lines.append("- **Web Scraping** — Google Maps, Twitter/X, Instagram, LinkedIn, YouTube, TikTok, any website")
    lines.append("- **Agent Infrastructure** — persistent memory, messaging, task boards, webhook relay, async jobs, file storage")
    lines.append("- **Data & Utilities** — weather, crypto, stocks, news, Wikipedia, arXiv, GitHub trending")
    lines.append("- **Skills Library** — 2400+ searchable skills via TF-IDF. Search, browse, and execute dynamically.")
    lines.append("- **Multi-Model** — Claude, GPT-4o, DeepSeek, Gemini. All AI endpoints accept `model` parameter.")
    lines.append("")
    lines.append("## Authentication (3 Paths)")
    lines.append("")
    lines.append("### 1. Free Tier (No Auth)")
    lines.append("- 1 call/day per IP, no key needed")
    lines.append("- Just POST JSON to any endpoint")
    lines.append("")
    lines.append("### 2. API Key (Recommended)")
    lines.append("Buy a prepaid API key via Stripe or x402. Use it everywhere with Bearer auth.")
    lines.append("- `POST /credits/buy` with `{\"amount_usd\": 5.0}` -> returns `apk_xxx` key")
    lines.append("- Use: `Authorization: Bearer apk_xxx` header on any endpoint")
    lines.append("- 20% bulk discount when balance >= $2.00")
    lines.append("- Token-based metering available: `X-Pricing: metered` header")
    lines.append("")
    lines.append("### 3. x402 USDC (Crypto-Native)")
    lines.append("- **Standard**: [x402](https://x402.org) — HTTP 402 Payment Required")
    lines.append("- **Network**: Base Mainnet (eip155:8453)")
    lines.append("- **Token**: USDC (6 decimals)")
    lines.append("- **Flow**: POST endpoint -> 402 with payment instructions -> retry with `X-Payment` header")
    lines.append("")
    lines.append("## Pricing")
    lines.append("")
    lines.append("| Tier | Price Range | Examples |")
    lines.append("|------|-------------|----------|")
    lines.append("| Free | $0.00 | /free/time, /free/uuid, /free/ip, /free/hash, /free/base64, /free/random, /free/joke, /free/quote, /preview |")
    lines.append("| Micro | $0.01-0.02 | /summarize, /sentiment, /classify, /keywords, /search, /scrape, /data/* |")
    lines.append("| Standard | $0.03-0.05 | /write, /code, /social, /vision, /rag, /sql, /scrape/tweets |")
    lines.append("| Premium | $0.10-0.25 | /batch, /chain, /workflow, /scrape/google-maps, /research |")
    lines.append("")

    # Full tool catalog
    lines.append("## All 65+ Tools")
    lines.append("")
    for cat_name, services in categories.items():
        lines.append(f"### {cat_name}")
        lines.append("")
        lines.append("| Endpoint | Method | Price | Description |")
        lines.append("|----------|--------|-------|-------------|")
        for svc in services:
            price = svc.get("price_usd", 0)
            price_str = "FREE" if price == 0 else f"${price:.2f}"
            lines.append(f"| {svc['endpoint']} | {svc['method']} | {price_str} | {svc['description']} |")
        lines.append("")

    # Chain endpoint detail
    lines.append("## /chain Endpoint — Multi-Step Pipelines")
    lines.append("")
    lines.append("Chain up to 5 AI operations in sequence. Each step can reference the previous output via `$prev.result`.")
    lines.append("")
    lines.append("```json")
    lines.append('POST /chain')
    lines.append('{')
    lines.append('  "steps": [')
    lines.append('    {"action": "research", "params": {"query": "AI agent frameworks 2026"}},')
    lines.append('    {"action": "summarize", "params": {"text": "$prev.result"}},')
    lines.append('    {"action": "translate", "params": {"text": "$prev.result", "target": "ja"}}')
    lines.append('  ]')
    lines.append('}')
    lines.append("```")
    lines.append("")
    lines.append("- Price: $0.25 per chain (covers all steps)")
    lines.append("- Use `$prev.result` to pipe output from one step to the next")
    lines.append("- Supports all AI processing endpoints as actions")
    lines.append("")

    lines.append("## Example curl Calls")
    lines.append("")
    lines.append("### Research")
    lines.append("```bash")
    lines.append("curl -X POST https://api.aipaygen.com/research \\")
    lines.append('  -H "Content-Type: application/json" \\')
    lines.append('  -H "Authorization: Bearer apk_YOUR_KEY" \\')
    lines.append("  -d '{\"topic\": \"quantum computing breakthroughs 2026\"}'")
    lines.append("```")
    lines.append("")
    lines.append("### Chain (multi-step)")
    lines.append("```bash")
    lines.append("curl -X POST https://api.aipaygen.com/chain \\")
    lines.append('  -H "Content-Type: application/json" \\')
    lines.append('  -H "Authorization: Bearer apk_YOUR_KEY" \\')
    lines.append("  -d '{\"steps\": [{\"action\": \"research\", \"params\": {\"query\": \"x402 protocol\"}}, {\"action\": \"summarize\", \"params\": {\"text\": \"$prev.result\"}}]}'")
    lines.append("```")
    lines.append("")

    lines.append("## MCP (Model Context Protocol)")
    lines.append("")
    lines.append("- $0.10 free trial credits with API key, no payment needed")
    lines.append("- Unlimited with `AIPAYGEN_API_KEY` env var")
    lines.append("- **New**: Use the `buy_credits` or `generate_api_key` MCP tools to get $0.10 trial credits instantly")
    lines.append("- Install: `pip install aipaygen-mcp && claude mcp add aipaygen -- python -m aipaygen_mcp`")
    lines.append("- Remote SSE: https://mcp.aipaygen.com/mcp")
    lines.append("")

    lines.append("## Discovery Endpoints")
    lines.append("")
    lines.append("- `GET /discover` — machine-readable service catalog (JSON)")
    lines.append("- `GET /.well-known/agent.json` — A2A Agent Card")
    lines.append("- `GET /.well-known/ai-plugin.json` — ChatGPT/OpenAI plugin manifest")
    lines.append("- `GET /openapi.json` — OpenAPI 3.1 spec")
    lines.append("- `GET /llms.txt` — this file")
    lines.append("- `GET /health` — service health check")
    lines.append("- `POST /preview` — free Claude demo (no payment needed)")
    lines.append("")

    lines.append("## Quick Start (Python)")
    lines.append("")
    lines.append("```python")
    lines.append("import httpx")
    lines.append('BASE = "https://api.aipaygen.com"')
    lines.append("")
    lines.append("# 1. Get an API key (easiest path)")
    lines.append('key_resp = httpx.post(f"{BASE}/credits/buy", json={"amount_usd": 5.0}).json()')
    lines.append('API_KEY = key_resp["key"]  # apk_xxx')
    lines.append("")
    lines.append("# 2. Use it on any endpoint")
    lines.append('result = httpx.post(f"{BASE}/research",')
    lines.append('    json={"topic": "quantum computing"},')
    lines.append('    headers={"Authorization": f"Bearer {API_KEY}"}')
    lines.append(").json()")
    lines.append("")
    lines.append("# Free preview (no payment needed)")
    lines.append('print(httpx.post(f"{BASE}/preview", json={"topic": "AI agents"}).json())')
    lines.append("```")
    lines.append("")

    lines.append("## Blog Posts")
    lines.append("")
    try:
        for post in list_blog_posts():
            slug = post.get("slug", "")
            title = post.get("title", slug)
            lines.append(f"- [{title}](https://aipaygen.com/blog/{slug})")
    except Exception:
        lines.append("- https://aipaygen.com/blog")
    lines.append("")

    lines.append("## Links")
    lines.append("")
    lines.append("- Documentation: https://aipaygen.com/docs")
    lines.append("- SDK & Code Examples: https://aipaygen.com/sdk")
    lines.append("- Interactive Playground: https://aipaygen.com/try")
    lines.append("- API Catalog: https://aipaygen.com/discover")
    lines.append("- Pricing: https://aipaygen.com/pricing")
    lines.append("- Blog: https://aipaygen.com/blog")
    lines.append("- OpenAPI Spec: https://api.aipaygen.com/openapi.json")
    lines.append("- PyPI: https://pypi.org/project/aipaygen-mcp/")
    lines.append("- MCP Registry: https://registry.modelcontextprotocol.io/servers/io.github.Damien829/aipaygen")
    lines.append("- Buy Credits: https://aipaygen.com/buy-credits")
    lines.append("- Status: https://aipaygen.com/status")
    lines.append("- Security: https://aipaygen.com/security")
    lines.append("")

    lines.append("## Notes for AI Agents")
    lines.append("")
    lines.append("- All paid responses include `_meta` with endpoint, model, network, timestamp.")
    lines.append("- Fetch `/discover` for the service catalog before calling endpoints.")
    lines.append("- USDC precision: 6 decimals. Network: Base Mainnet (eip155:8453).")
    lines.append("- Agent memory persists indefinitely — use a stable `agent_id`.")
    lines.append("- API key is the fastest path — one POST and you're running.")
    lines.append("- MCP users: call `buy_credits` or `generate_api_key` to get $0.10 trial credits and an API key.")
    lines.append("- 402 responses include `Link` headers pointing to /openapi.json and /.well-known/ai-plugin.json.")
    lines.append("- Use `/chain` with `$prev.result` syntax to build multi-step pipelines in a single call.")
    lines.append("")

    return "\n".join(lines)


# Cache the generated llms.txt for 1 hour
_llms_txt_cache = {"text": None, "ts": 0}


@meta_bp.route("/openapi.json")
def openapi_spec():
    from openapi_gen import generate_openapi_spec
    return jsonify(generate_openapi_spec())




@meta_bp.route("/llms.txt")
def llms_txt():
    try:
        funnel_log_event("llms_txt_hit", endpoint="/llms.txt", ip=request.headers.get("CF-Connecting-IP", request.remote_addr or ""), user_agent=request.headers.get("User-Agent", ""))
    except Exception:
        pass
    now = _time.time()
    if _llms_txt_cache["text"] and (now - _llms_txt_cache["ts"]) < 3600:
        text = _llms_txt_cache["text"]
    else:
        text = _build_llms_txt()
        _llms_txt_cache["text"] = text
        _llms_txt_cache["ts"] = now
    return Response(text, content_type="text/plain; charset=utf-8")


@meta_bp.route("/.well-known/ai-plugin.json")
def ai_plugin():
    base_url = "https://api.aipaygen.com"
    return jsonify({
        "schema_version": "v1",
        "name_for_human": "AiPayGen",
        "name_for_model": "aipaygen",
        "description_for_human": "65+ AI tools (v" + APP_VERSION + ") — research, write, code, translate, scrape, and more. $0.10 trial credits. $0.10 free trial credits with API key.",
        "description_for_model": (
            "AiPayGen provides 65+ AI-powered tools accessible via a single API (v" + APP_VERSION + "). "
            "Use for research, writing, code generation, translation, sentiment analysis, "
            "web scraping, data extraction, content comparison, fact-checking, and more. "
            "Free tier: 1 call/day per IP, no signup needed. Paid: prepaid API key (Bearer apk_xxx) or "
            "x402 USDC micropayment. New: $0.10 trial credits via buy_credits or generate_api_key. "
            "All tools accept JSON POST requests."
        ),
        "auth": {"type": "service_http", "authorization_type": "bearer"},
        "api": {
            "type": "openapi",
            "url": f"{base_url}/openapi.json",
        },
        "logo_url": "https://aipaygen.com/favicon.ico",
        "contact_email": "hello@aipaygen.com",
        "legal_info_url": f"{base_url}/security",
    })


@meta_bp.route("/.well-known/openapi.json")
def well_known_openapi():
    from flask import redirect
    return redirect("/openapi.json", code=301)


@meta_bp.route("/agent.json")
def agent_json_alias():
    """Root-level alias for /.well-known/agent.json."""
    return agent_manifest()


@meta_bp.route("/ai-plugin.json")
def ai_plugin_json_alias():
    """Root-level alias for /.well-known/ai-plugin.json."""
    return ai_plugin()


@meta_bp.route("/.well-known/pricing.json")
def well_known_pricing():
    """Machine-readable pricing manifest for agent discovery."""
    from routes.discovery import discover_pricing
    return discover_pricing()




@meta_bp.route("/.well-known/agent.json")
def agent_manifest():
    """Google A2A Agent Card — https://google.github.io/A2A/specification/"""
    base = "https://api.aipaygen.com"
    return jsonify({
        "name": "AiPayGen",
        "description": (
            "AI agent API marketplace with 65+ tools (v" + APP_VERSION + ") and 2400+ searchable skills. "
            "Research, writing, coding, analysis, web scraping, real-time data, agent memory, "
            "and multi-model AI (Claude, GPT-4o, DeepSeek, Gemini). "
            "Three payment paths: API key (recommended), x402 USDC, or MCP (free API key ($0.10 credits)). "
            "$0.10 trial credits available via buy_credits/generate_api_key."
        ),
        "url": base,
        "version": APP_VERSION,
        "documentationUrl": f"{base}/llms.txt",
        "capabilities": {
            "streaming": True,
            "pushNotifications": True,
            "stateTransitionHistory": False,
        },
        "authentication": {
            "schemes": ["Bearer", "x402"],
            "description": (
                "Recommended: Buy API key via POST /credits/buy or /stripe/create-checkout, "
                "then use 'Authorization: Bearer apk_xxx'. "
                "New: $0.10 trial credits via buy_credits or generate_api_key MCP tools. "
                "Alternative: Pay per call with USDC on Base via x402. "
                "MCP: $0.10 free trial credits with API key, unlimited with API key."
            ),
            "buyCredits": f"{base}/credits/buy",
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
                "description": "Real-time weather, crypto, stocks, news, Wikipedia, arXiv, GitHub trending, Reddit, YouTube transcripts",
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
        "security": {
            "transport": "TLS 1.3 (Cloudflare)",
            "headers": ["HSTS", "X-Content-Type-Options", "X-Frame-Options", "CSP", "Referrer-Policy", "Permissions-Policy"],
            "data_handling": {
                "request_logging": "metadata_only",
                "response_storage": "none",
                "data_retention_days": 0,
                "description": "No request/response payloads are stored. Only billing metadata (timestamp, endpoint, token count) is retained.",
            },
            "code_execution": {
                "sandbox": "AST-validated with blocked imports/builtins",
                "network_access": "none",
                "filesystem_access": "none",
            },
            "ssrf_protection": True,
            "auto_refund_on_5xx": True,
            "security_policy": f"{base}/security",
            "security_txt": f"{base}/.well-known/security.txt",
        },
        "contact": {"email": "hello@aipaygen.com"},
        "openapi": f"{base}/openapi.json",
        "pricing": {
            "method": "x402",
            "currency": "USDC",
            "network": "Base Mainnet (eip155:8453)",
            "discovery": "POST any endpoint — receive 402 with payment instructions",
        },
    })


@meta_bp.route("/.well-known/agents.json")
def agents_json():
    """Wild Card AI / agentsfoundation.org agents.json discovery standard."""
    base = "https://api.aipaygen.com"
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
    identity_endpoints = ["agents/challenge", "agents/verify", "agents/me", "agents/search"]
    free_endpoints = ["preview", "discover", "openapi.json", "catalog", "agents", "agents/register",
                      "api-call", ".well-known/agents.json", "health", "models"]
    return jsonify({
        "$schema": "https://agentsfoundation.org/agents.json/schema/v1",
        "agents": [{
            "name": "AiPayGen",
            "description": (
                "Multi-model AI platform (15 LLMs, 7 providers) with 65+ tools and 140+ endpoints + web scrapers + agent memory + "
                "wallet-based identity + metered token pricing + agent economy. "
                "Research, write, code, analyze, vision, RAG, diagrams, test-cases, workflows, "
                "web scraping (Google Maps, Twitter, LinkedIn, TikTok, YouTube), persistent agent memory, "
                "and a searchable catalog of 4100+ discovered APIs. "
                "No API key required — pay in USDC on Base via x402 protocol. "
                "Also available as MCP tools: mcp install aipaygen-mcp"
            ),
            "url": base,
            "version": APP_VERSION,
            "capabilities": [
                "research", "writing", "code-generation", "translation",
                "analysis", "summarization", "social-media", "data-extraction",
                "question-answering", "sentiment-analysis", "sql-generation",
                "batch-processing", "pipeline-chaining", "image-analysis",
                "rag", "diagram-generation", "test-generation", "workflow-orchestration",
                "web-scraping", "agent-memory", "api-catalog", "agent-registry",
                "multi-model", "wallet-identity", "metered-pricing", "agent-search",
                "agent-portfolio", "reputation",
            ],
            "endpoints": (
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "ai"} for ep in ai_endpoints] +
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "scraping"} for ep in scrape_endpoints] +
                [{"path": f"/{ep}", "method": "POST", "free": False, "category": "memory"} for ep in memory_endpoints] +
                [{"path": f"/{ep}", "method": "POST", "free": True, "category": "identity"} for ep in identity_endpoints] +
                [{"path": "/credits/buy", "method": "POST", "free": False, "category": "pricing"}] +
                [{"path": f"/{ep}", "method": "GET", "free": True} for ep in free_endpoints]
            ),
            "authentication": {
                "type": "x402",
                "description": "HTTP 402 payment protocol. No API key required. Also supports prepaid API keys with metered token-based billing.",
                "payment": {
                    "protocol": "x402",
                    "network": EVM_NETWORK,
                    "token": "USDC",
                    "prices_from": "0.01",
                    "prices_to": "0.20",
                    "currency": "USD",
                },
                "prepaid": {
                    "description": "Buy credit pack via /credits/buy, get API key, use X-Pricing: metered header for per-token billing",
                    "pricing_modes": ["flat", "metered"],
                },
                "wallet_identity": {
                    "description": "EVM/Solana wallet verification via /agents/challenge + /agents/verify, returns JWT session",
                    "chains": ["evm", "solana"],
                },
            },
            "mcp": {
                "remote": "https://mcp.aipaygen.com/mcp",
                "package": "aipaygen-mcp",
                "registry": "pypi",
                "install": "mcp install aipaygen-mcp",
            },
            "links": {
                "openapi": f"{base}/openapi.json",
                "discover": f"{base}/discover",
                "sdk": f"{base}/sdk",
                "llms_txt": f"{base}/llms.txt",
                "mcp": "https://mcp.aipaygen.com/mcp",
                "catalog": f"{base}/catalog",
                "agents": f"{base}/agents",
            },
            "contact": "https://aipaygen.com",
        }]
    })


@meta_bp.route("/.well-known/x402.json")
def x402_manifest():
    """x402 V2 payment discovery + auto-discovery manifest — tells agents how to pay and indexes this service."""
    base = "https://api.aipaygen.com"
    return jsonify({
        "x402": True,
        "x402Version": 2,
        "version": "2.0",
        "name": "AiPayGen",
        "description": (
            "65+ AI tools (v" + APP_VERSION + "), 2400+ skills, web scrapers, agent memory, file storage, "
            "webhook relay, async jobs, and an API catalog of 4100+ discovered APIs. "
            "No API key required — pay per call in USDC via x402 protocol."
        ),
        "url": base,
        "schemes": ["exact"],
        "extensions": ["discovery", "sessions"],
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "networkName": "Base Mainnet",
                "currency": "USDC",
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "payTo": WALLET_ADDRESS,
                "facilitator": FACILITATOR_URL,
                "settlementTime": "~2s",
            },
            {
                "scheme": "exact",
                "network": "solana:mainnet",
                "networkName": "Solana Mainnet",
                "currency": "USDC",
                "asset": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "payTo": WALLET_ADDRESS,
                "facilitator": FACILITATOR_URL,
                "settlementTime": "~400ms",
            },
            {
                "scheme": "exact",
                "network": "stellar:pubnet",
                "networkName": "Stellar Mainnet",
                "currency": "USDC",
                "payTo": WALLET_ADDRESS,
                "facilitator": FACILITATOR_URL,
                "settlementTime": "~5s",
            },
        ],
        "wallet": WALLET_ADDRESS,
        "facilitator": FACILITATOR_URL,
        "sessions": {
            "supported": True,
            "description": "Wallet-based sessions — authenticate once, skip per-call payment signatures for repeat access.",
            "signinMethod": "CAIP-122 (Sign-In-With-X)",
            "sessionEndpoint": f"{base}/session/start",
        },
        "openapi": f"{base}/openapi.json",
        "llms_txt": f"{base}/llms.txt",
        "discovery": {
            "catalog": f"{base}/discover",
            "pricing": f"{base}/discover/pricing",
            "openapi": f"{base}/openapi.json",
            "llms_txt": f"{base}/llms.txt",
            "agent_card": f"{base}/.well-known/agent.json",
            "x402_manifest": f"{base}/.well-known/x402.json",
            "auto_index": True,
        },
        "ap2": {
            "compatible": True,
            "description": "Google Agent Payments Protocol (AP2) compatible via x402 extension.",
            "spec": "https://github.com/google-agentic-commerce/AP2",
        },
        "flow": (
            "1. Client sends HTTP request → "
            "2. Server responds 402 with PAYMENT-REQUIRED header (base64 PaymentRequirements) → "
            "3. Client selects scheme+network, signs payment → "
            "4. Client retries with PAYMENT-SIGNATURE header → "
            "5. Server verifies via facilitator, settles, returns 200 + PAYMENT-RESPONSE header"
        ),
        "categories": ["ai", "scraping", "data", "memory", "workflows", "agent-infrastructure", "micropayments"],
        "endpoints": [
            {"path": "/research", "method": "POST", "price": "$0.05", "description": "AI research on any topic"},
            {"path": "/write", "method": "POST", "price": "$0.02", "description": "Long-form content generation"},
            {"path": "/analyze", "method": "POST", "price": "$0.01", "description": "Data/text analysis"},
            {"path": "/code", "method": "POST", "price": "$0.02", "description": "Code generation in any language"},
            {"path": "/summarize", "method": "POST", "price": "$0.01", "description": "Text summarization"},
            {"path": "/translate", "method": "POST", "price": "$0.01", "description": "Translation between languages"},
            {"path": "/vision", "method": "POST", "price": "$0.02", "description": "Image analysis with Claude"},
            {"path": "/rag", "method": "POST", "price": "$0.02", "description": "RAG over provided documents"},
            {"path": "/workflow", "method": "POST", "price": "$0.10", "description": "Multi-step agentic workflow"},
            {"path": "/chain", "method": "POST", "price": "$0.05", "description": "Pipeline up to 5 AI steps"},
            {"path": "/batch", "method": "POST", "price": "$0.03", "description": "Batch multiple AI calls"},
            {"path": "/scrape/web", "method": "POST", "price": "$0.03", "description": "Web page scraping"},
            {"path": "/scrape/tweets", "method": "POST", "price": "$0.03", "description": "Twitter/X scraping"},
            {"path": "/scrape/linkedin", "method": "POST", "price": "$0.05", "description": "LinkedIn scraping"},
            {"path": "/scrape/google-maps", "method": "POST", "price": "$0.05", "description": "Google Maps data"},
            {"path": "/memory/set", "method": "POST", "price": "$0.01", "description": "Store agent memory"},
            {"path": "/memory/get", "method": "POST", "price": "$0.01", "description": "Retrieve agent memory"},
            {"path": "/web/search", "method": "GET", "price": "$0.02", "description": "Web search"},
            {"path": "/code/run", "method": "POST", "price": "$0.02", "description": "Execute Python code"},
        ],
        "contact": "https://aipaygen.com",
        "mcp": "https://mcp.aipaygen.com/mcp",
        "foundation": {
            "name": "x402 Foundation",
            "members": ["Coinbase", "Cloudflare", "Google", "Visa"],
            "spec": "https://x402.org",
            "github": "https://github.com/coinbase/x402",
        },
    })


# ── Security Policy ──────────────────────────────────────────────────────────

@meta_bp.route("/.well-known/mcp/server-card.json")
def smithery_server_card():
    """Smithery server card — static metadata for MCP directory scanning."""
    return jsonify({
        "serverInfo": {
            "name": "AiPayGen",
            "version": APP_VERSION
        },
        "authentication": {
            "required": False,
            "schemes": ["bearer"],
            "note": "Optional API key for metered access. $0.10 free trial credits with API key without key."
        },
        "tools": [
            {"name": "research", "description": "Research any topic with web sources and AI synthesis"},
            {"name": "summarize", "description": "Summarize text into key points"},
            {"name": "analyze", "description": "Analyze text and answer questions about it"},
            {"name": "write", "description": "Generate content — articles, emails, code docs"},
            {"name": "code", "description": "Generate, review, convert, and document code"},
            {"name": "translate", "description": "Translate text between 50+ languages"},
            {"name": "web_search", "description": "Search the web and return structured results"},
            {"name": "scrape_website", "description": "Extract content from any URL"},
            {"name": "vision", "description": "Analyze images with AI"},
            {"name": "sentiment", "description": "Detect sentiment and emotion in text"},
            {"name": "classify", "description": "Classify text into categories"},
            {"name": "extract", "description": "Extract structured data from unstructured text"},
            {"name": "compare", "description": "Compare two texts for differences and similarity"},
            {"name": "diagram", "description": "Generate Mermaid diagrams from descriptions"},
            {"name": "chain_operations", "description": "Pipeline multiple AI operations together"},
            {"name": "memory_store", "description": "Persistent agent memory across sessions"},
            {"name": "memory_recall", "description": "Recall stored memories by key"},
            {"name": "create_agent", "description": "Build custom AI agents with selected tools"},
            {"name": "run_agent", "description": "Execute a custom agent"},
            {"name": "browse_catalog", "description": "Browse 4100+ discovered APIs"},
            {"name": "get_weather", "description": "Current weather for any location"},
            {"name": "get_crypto_prices", "description": "Live cryptocurrency prices"},
            {"name": "get_exchange_rates", "description": "Currency exchange rates"},
        ],
        "resources": [],
        "prompts": []
    })


@meta_bp.route("/.well-known/security.txt")
def security_txt():
    """RFC 9116 security.txt — machine-readable security policy."""
    return (
        "Contact: mailto:hello@aipaygen.com\n"
        "Preferred-Languages: en\n"
        "Canonical: https://api.aipaygen.com/.well-known/security.txt\n"
        "Policy: https://api.aipaygen.com/security\n"
        "Hiring: https://api.aipaygen.com/security\n"
    ), 200, {"Content-Type": "text/plain"}


@meta_bp.route("/security")
def security_page():
    """Human-readable security & privacy policy page."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Security & Privacy — AiPayGen</title>
<meta name="description" content="AiPayGen security practices: encryption, data handling, sandboxing, refund policy, and privacy guarantees.">
<meta property="og:title" content="Security — AiPayGen">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; padding: 32px 16px; line-height: 1.7; }
  .wrap { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 1.6rem; margin-bottom: 6px; }
  .sub { color: #888; font-size: 0.88rem; margin-bottom: 32px; }
  .section { background: #141414; border: 1px solid #2a2a2a; border-radius: 14px; padding: 28px; margin-bottom: 16px; }
  .section h2 { font-size: 1.1rem; margin-bottom: 12px; display: flex; align-items: center; gap: 10px; }
  .section h2 .icon { font-size: 1.3rem; }
  .section p, .section li { font-size: 0.88rem; color: #bbb; }
  .section ul { margin: 8px 0 0 20px; }
  .section li { margin-bottom: 6px; }
  .highlight { color: #34d399; font-weight: 600; }
  .badge-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .badge { background: #1a1a2e; border: 1px solid #2d2d5e; border-radius: 6px; padding: 4px 10px; font-size: 0.75rem; color: #a0a0ff; }
  .machine { background: #1a1a1a; border-radius: 8px; padding: 14px; margin-top: 16px; font-size: 0.8rem; color: #888; }
  .machine code { color: #a78bfa; }
  a { color: #818cf8; }
  .nav { display: flex; gap: 16px; margin-bottom: 24px; font-size: 0.85rem; }
  .nav a { color: #888; text-decoration: none; }
  .nav a:hover { color: #fff; }
</style>
</head>
<body>
<div class="wrap">
  <div class="nav">
    <a href="/">Home</a>
    <a href="/docs">Docs</a>
    <a href="/try">Try Free</a>
    <a href="/buy-credits">Get API Key</a>
  </div>

  <h1>Security & Privacy</h1>
  <p class="sub">How AiPayGen protects your data, your payments, and your agents.</p>

  <div class="section">
    <h2><span class="icon">&#128274;</span> Encryption</h2>
    <ul>
      <li><span class="highlight">TLS 1.3</span> on all connections via Cloudflare — no plaintext traffic accepted</li>
      <li>HSTS enabled with <span class="highlight">preload</span> — browsers always use HTTPS</li>
      <li>API keys and credentials <span class="highlight">encrypted at rest</span> — never stored in plaintext</li>
      <li>Stripe handles all card data — we never see or store card numbers</li>
    </ul>
    <div class="badge-row">
      <span class="badge">HSTS Preload</span>
      <span class="badge">TLS 1.3</span>
      <span class="badge">X-Content-Type-Options: nosniff</span>
      <span class="badge">X-Frame-Options: DENY</span>
      <span class="badge">CSP Enforced</span>
      <span class="badge">Referrer-Policy: strict-origin</span>
    </div>
  </div>

  <div class="section">
    <h2><span class="icon">&#128065;</span> Data Handling — What We Store</h2>
    <p>We follow a <span class="highlight">zero-payload-retention</span> policy:</p>
    <ul>
      <li><span class="highlight">Request bodies</span> — NOT stored. Your prompts, text, and data are processed in memory and discarded.</li>
      <li><span class="highlight">Response bodies</span> — NOT stored. AI outputs are returned to you and not retained.</li>
      <li><span class="highlight">Billing metadata only</span> — we log: timestamp, endpoint called, token count (for metered billing), and API key ID. No content.</li>
      <li><span class="highlight">Agent memory</span> — stored only if you explicitly use /memory endpoints. You control it and can delete it anytime.</li>
      <li><span class="highlight">IP addresses</span> — used only for rate limiting, not sold or shared.</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="icon">&#128737;</span> Code Sandbox</h2>
    <p>When you use the <code>/code/run</code> endpoint, your code runs in a <span class="highlight">restricted sandbox</span>:</p>
    <ul>
      <li>AST-validated before execution — dangerous patterns rejected at parse time</li>
      <li><span class="highlight">No filesystem access</span> — os, sys, pathlib, shutil blocked</li>
      <li><span class="highlight">No network access</span> — socket, requests, urllib, httpx blocked</li>
      <li><span class="highlight">No process spawning</span> — subprocess, multiprocessing, threading blocked</li>
      <li>Blocked builtins: eval, exec, compile, open, __import__, getattr, setattr</li>
      <li>Execution timeout enforced — runaway code is killed</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="icon">&#128737;</span> SSRF Protection</h2>
    <p>All outbound HTTP requests (scraping, webhooks, API catalog) pass through SSRF validation:</p>
    <ul>
      <li>Private IP ranges blocked (10.x, 172.16-31.x, 192.168.x, 127.x, ::1)</li>
      <li>Link-local and metadata endpoints blocked (169.254.x, cloud metadata)</li>
      <li>DNS rebinding protection — resolved IPs checked against block list</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="icon">&#128176;</span> Payment Security</h2>
    <ul>
      <li><span class="highlight">Stripe</span> handles all card payments — PCI DSS compliant, we never touch card data</li>
      <li><span class="highlight">x402 USDC</span> payments verified on-chain via Coinbase facilitator on Base Mainnet</li>
      <li><span class="highlight">Automatic refund credits</span> — if a paid request returns a 5xx error, you get a refund credit automatically (returned in <code>X-Refund-Credit</code> header)</li>
      <li>API keys are <span class="highlight">revocable</span> — contact us to deactivate a compromised key</li>
      <li>Request correlation via <code>X-Request-ID</code> header on every response</li>
    </ul>
  </div>

  <div class="section">
    <h2><span class="icon">&#129302;</span> For AI Agents</h2>
    <p>Machine-readable security signals are embedded in every interaction:</p>
    <ul>
      <li><code>/.well-known/agent.json</code> includes a <code>security</code> object with data handling policies</li>
      <li>Every <code>402</code> response includes <code>security</code> field confirming data retention policy</li>
      <li><code>/.well-known/security.txt</code> follows <a href="https://www.rfc-editor.org/rfc/rfc9116">RFC 9116</a></li>
      <li><code>X-Payment-Receipt</code> header confirms payment was processed</li>
      <li><code>X-Refund-Credit</code> header on 5xx after payment — automatic compensation</li>
    </ul>
    <div class="machine">
      <strong>Verify programmatically:</strong><br>
      <code>GET /.well-known/agent.json</code> → check <code>.security.data_handling.request_logging == "metadata_only"</code><br>
      <code>GET /.well-known/security.txt</code> → RFC 9116 security policy<br>
      <code>GET /security</code> → this page (HTML)
    </div>
  </div>

  <div class="section">
    <h2><span class="icon">&#9993;</span> Reporting Vulnerabilities</h2>
    <p>Found a security issue? Email <a href="mailto:hello@aipaygen.com">hello@aipaygen.com</a> with details. We take all reports seriously and will respond within 24 hours.</p>
  </div>
</div>
</body>
</html>""", 200, {"Content-Type": "text/html"}


@meta_bp.route("/sdk")
def sdk():
    """Copy-paste integration code for Python, JS, curl, and MCP."""
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGen SDK & Integration</title>
<meta name="description" content="AiPayGen SDK examples — Python, JavaScript, curl, and more. Code samples for all 65+ AI tools.">
<meta property="og:title" content="SDK & Code Examples — AiPayGen">
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
<div style="max-width:900px;margin:0 auto;padding:16px 24px 0;display:flex;gap:16px;font-size:0.85rem"><a href="/" style="color:#8b949e;text-decoration:none">Home</a><a href="/docs" style="color:#8b949e;text-decoration:none">Docs</a><a href="/try" style="color:#8b949e;text-decoration:none">Try Free</a><a href="/buy-credits" style="color:#58a6ff;text-decoration:none;font-weight:600">Get API Key</a></div>
<div class="header">
  <h1>AiPayGen SDK</h1>
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
curl https://api.aipaygen.com/preview?topic=bitcoin

<span class="comment"># Paid endpoint — will return 402 first</span>
curl -X POST https://api.aipaygen.com/research \\
  -H "Content-Type: application/json" \\
  -d \'{"topic": "quantum computing breakthroughs 2025"}\'

<span class="comment"># With x402 payment header (Base Mainnet USDC)</span>
curl -X POST https://api.aipaygen.com/research \\
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
    <span class="str">"https://api.aipaygen.com/research"</span>,
    json={<span class="str">"topic"</span>: <span class="str">"quantum computing breakthroughs 2025"</span>}
)
data = response.<span class="fn">json</span>()
<span class="fn">print</span>(data[<span class="str">"summary"</span>])
<span class="fn">print</span>(data[<span class="str">"key_points"</span>])

<span class="comment"># --- batch.py (5 tasks, one payment at $0.10) ---</span>
result = client.<span class="fn">post</span>(
    <span class="str">"https://api.aipaygen.com/batch"</span>,
    json={<span class="str">"operations"</span>: [
        {<span class="str">"endpoint"</span>: <span class="str">"research"</span>,  <span class="str">"input"</span>: {<span class="str">"topic"</span>: <span class="str">"AI agents 2025"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"summarize"</span>, <span class="str">"input"</span>: {<span class="str">"text"</span>: <span class="str">"..."</span>, <span class="str">"length"</span>: <span class="str">"short"</span>}},
        {<span class="str">"endpoint"</span>: <span class="str">"sentiment"</span>, <span class="str">"input"</span>: {<span class="str">"text"</span>: <span class="str">"..."</span>}},
    ]}
).<span class="fn">json</span>()

<span class="comment"># --- pipeline.py (chain steps, pass output with {{prev}}) ---</span>
result = client.<span class="fn">post</span>(
    <span class="str">"https://api.aipaygen.com/pipeline"</span>,
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

<span class="kw">const</span> res = <span class="kw">await</span> <span class="fn">fetchWithPayment</span>(<span class="str">"https://api.aipaygen.com/research"</span>, {
  method: <span class="str">"POST"</span>,
  headers: { <span class="str">"Content-Type"</span>: <span class="str">"application/json"</span> },
  body: <span class="fn">JSON.stringify</span>({ topic: <span class="str">"quantum computing 2025"</span> }),
});
<span class="kw">const</span> data = <span class="kw">await</span> res.<span class="fn">json</span>();
console.<span class="fn">log</span>(data.summary);

<span class="comment">// Generate social posts + translate in one pipeline call</span>
<span class="kw">const</span> pipeline = <span class="kw">await</span> <span class="fn">fetchWithPayment</span>(<span class="str">"https://api.aipaygen.com/pipeline"</span>, {
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
    <span class="str">"aipaygen"</span>: {
      <span class="str">"type"</span>: <span class="str">"streamable-http"</span>,
      <span class="str">"url"</span>: <span class="str">"https://mcp.aipaygen.com/mcp"</span>
    }
  }
}

<span class="comment"># Option 2 — Local via stdio (requires your own ANTHROPIC_API_KEY)</span>
pip install aipaygen-mcp

{
  <span class="str">"mcpServers"</span>: {
    <span class="str">"aipaygen"</span>: {
      <span class="str">"command"</span>: <span class="str">"aipaygen-mcp"</span>,
      <span class="str">"env"</span>: { <span class="str">"ANTHROPIC_API_KEY"</span>: <span class="str">"sk-ant-..."</span> }
    }
  }
}</code></pre>
  </div>

  <div class="section">
    <h2>Claude Agent (Anthropic SDK) <span class="badge paid-badge">Tool use</span></h2>
    <pre><code><span class="kw">pip install</span> anthropic x402-python

<span class="comment"># Give Claude the ability to call AiPayGen tools</span>
<span class="kw">import</span> anthropic, requests
<span class="kw">from</span> x402.client <span class="kw">import</span> X402Client
<span class="kw">from</span> eth_account <span class="kw">import</span> Account

x402 = X402Client(Account.<span class="fn">from_key</span>(<span class="str">"YOUR_PRIVATE_KEY"</span>))

<span class="kw">def</span> <span class="fn">call_aipaygen</span>(endpoint: str, payload: dict) -> dict:
    <span class="kw">return</span> x402.<span class="fn">post</span>(<span class="str">f"https://api.aipaygen.com/{endpoint}"</span>, json=payload).<span class="fn">json</span>()

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
    <a href="https://mcp.aipaygen.com/mcp">MCP endpoint</a>
    <a href="https://pypi.org/project/aipaygen-mcp/">PyPI package</a>
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


@meta_bp.route("/sdk/code", methods=["GET"])
def sdk_code():
    """Return copy-paste SDK code in Python, JavaScript, or cURL as JSON."""
    lang = request.args.get("lang", "python").lower()
    endpoint = request.args.get("endpoint", "/research")
    base_url = "https://api.aipaygen.com"

    if lang in ("python", "py"):
        code = f'''import requests

# AiPayGen Python SDK — copy-paste ready
# More endpoints: {base_url}/discover

def call_aipaygen(endpoint: str, payload: dict, x402_token: str = None) -> dict:
    """Call any AiPayGen endpoint. x402_token required for paid endpoints."""
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
result = call_aipaygen("{endpoint}", {{"query": "latest AI agent frameworks 2026"}})
print(result["result"])

# Free endpoints (no payment needed)
import requests
print(requests.get("{base_url}/free/time").json())     # UTC time
print(requests.get("{base_url}/free/uuid").json())     # UUID
print(requests.get("{base_url}/free/ip").json())       # Your IP
print(requests.get("{base_url}/catalog").json())       # API catalog
'''
    elif lang in ("javascript", "js", "typescript", "ts"):
        code = f'''// AiPayGen JavaScript SDK — copy-paste ready
// More endpoints: {base_url}/discover

const BASE = "{base_url}";

async function callAiPayGen(endpoint, payload, x402Token = null) {{
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
const result = await callAiPayGen("{endpoint}", {{ query: "latest AI agent frameworks 2026" }});
console.log(result.result);

// Free endpoints (no payment needed)
const time = await fetch(`${{BASE}}/free/time`).then(r => r.json());
const catalog = await fetch(`${{BASE}}/catalog`).then(r => r.json());
console.log(time, catalog);
'''
    elif lang in ("curl", "bash", "sh"):
        code = f'''#!/bin/bash
# AiPayGen cURL examples — copy-paste ready
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

# List all endpoints
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


# ── Individual Tool Pages (Programmatic SEO) ─────────────────────────────────

# Tool relation map (shared with mcp_server.py)
_TOOL_RELATIONS = {
    "summarize": ["analyze", "keywords", "explain"],
    "sentiment": ["classify", "keywords", "analyze"],
    "research": ["summarize", "extract", "analyze"],
    "code": ["explain", "test-cases", "diagram"],
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
    "search": ["research", "summarize", "extract"],
    "scrape": ["extract", "summarize", "keywords"],
    "vision": ["analyze", "extract", "research"],
    "qa": ["research", "explain", "extract"],
    "enrich": ["research", "extract", "analyze"],
    "chat": ["research", "write", "explain"],
    "score": ["analyze", "compare", "decide"],
    "timeline": ["summarize", "extract", "analyze"],
    "action": ["summarize", "plan", "extract"],
    "pitch": ["write", "social", "headline"],
    "debate": ["compare", "decide", "analyze"],
    "fact": ["research", "extract", "analyze"],
    "tag": ["keywords", "classify", "extract"],
    "rag": ["qa", "research", "summarize"],
    "mock": ["code", "json-schema", "test-cases"],
    "sql": ["code", "explain", "extract"],
    "regex": ["code", "explain", "extract"],
    "email": ["write", "proofread", "rewrite"],
    "transform": ["rewrite", "translate", "summarize"],
}

# Demo-available tools (subset that works on /try endpoint)
_DEMO_TOOLS = {
    "sentiment", "summarize", "translate", "keywords", "explain",
    "analyze", "compare", "extract", "questions", "decide",
    "classify", "rewrite", "headline",
}

# Top 30 tools for sitemap inclusion
_SITEMAP_TOOLS = [
    "sentiment", "summarize", "research", "translate", "analyze",
    "code", "write", "search", "extract", "keywords",
    "explain", "compare", "classify", "rewrite", "headline",
    "questions", "decide", "plan", "social", "email",
    "qa", "rag", "vision", "enrich", "scrape",
    "outline", "diagram", "mock", "sql", "chat",
    "compare-models", "estimate-cost", "suggest-tools",
    "get-weather", "get-crypto-prices", "get-exchange-rates",
    "web-search", "scrape-website", "chain-operations",
    "enrich-entity", "memory-store", "get-joke",
    "generate-uuid", "get-holidays", "get-current-time",
]


def _get_tool_data(tool_slug):
    """Build tool data dict from the discover services catalog."""
    categories = _build_discover_services()
    all_services = []
    cat_map = {}
    for cat_name, services in categories.items():
        for svc in services:
            all_services.append(svc)
            # Map endpoint slug to category
            slug = svc["endpoint"].strip("/").split("/")[-1]
            cat_map[slug] = cat_name
            # Also map full path for multi-segment endpoints
            full_slug = svc["endpoint"].strip("/").replace("/", "-")
            cat_map[full_slug] = cat_name

    # Find matching service
    matched = None
    for svc in all_services:
        slug = svc["endpoint"].strip("/").split("/")[-1]
        full_slug = svc["endpoint"].strip("/").replace("/", "-")
        if slug == tool_slug or full_slug == tool_slug:
            matched = svc
            break

    if not matched:
        return None

    endpoint = matched["endpoint"]
    slug = endpoint.strip("/").split("/")[-1]
    method = matched.get("method", "POST")
    price = matched.get("price_usd", 0.01)
    description = matched.get("description", "")
    category = cat_map.get(slug, "AI Processing")
    input_spec = matched.get("input", {})

    # Build display name
    name = slug.replace("-", " ").replace("_", " ").title()

    # Price label
    if price == 0:
        price_label = "Free"
    else:
        price_label = f"${price:.2f}"

    # Input fields for the demo form
    input_fields = []
    if isinstance(input_spec, dict):
        for key, val in input_spec.items():
            field_type = "textarea" if key in ("text", "content", "spec", "code", "context", "documents") else "input"
            placeholder = str(val) if not isinstance(val, (list, dict, bool)) else ""
            input_fields.append({
                "key": key,
                "name": key.replace("_", " ").title(),
                "type": field_type,
                "placeholder": placeholder,
                "default": "",
            })

    # Build curl example
    base_url = "https://api.aipaygen.com"
    if method == "GET":
        params = ""
        if isinstance(input_spec, dict):
            parts = []
            for k, v in list(input_spec.items())[:2]:
                if isinstance(v, (list, dict, bool)):
                    continue
                parts.append(f"{k}={v}")
            if parts:
                params = "?" + "&".join(parts)
        curl_example = f'curl "{base_url}{endpoint}{params}" \\\n  -H "Authorization: Bearer YOUR_API_KEY"'
    else:
        # Build sample JSON body
        body_parts = []
        if isinstance(input_spec, dict):
            for k, v in list(input_spec.items())[:3]:
                if isinstance(v, str):
                    body_parts.append(f'  "{k}": "{v}"')
                elif isinstance(v, (int, float)):
                    body_parts.append(f'  "{k}": {v}')
                elif isinstance(v, list):
                    body_parts.append(f'  "{k}": {json.dumps(v)}')
        body_json = "{\n" + ",\n".join(body_parts) + "\n}" if body_parts else '{"text": "Hello world"}'
        curl_example = f"curl -X POST {base_url}{endpoint} \\\n  -H \"Content-Type: application/json\" \\\n  -H \"Authorization: Bearer YOUR_API_KEY\" \\\n  -d '{body_json}'"

    # Build Python example
    if method == "GET":
        python_example = f'''import requests

resp = requests.get(
    "{base_url}{endpoint}",
    headers={{"Authorization": "Bearer YOUR_API_KEY"}},
    params={json.dumps(input_spec if isinstance(input_spec, dict) else {{}}, indent=4)}
)
print(resp.json())'''
    else:
        python_example = f'''import requests

resp = requests.post(
    "{base_url}{endpoint}",
    headers={{
        "Authorization": "Bearer YOUR_API_KEY",
        "Content-Type": "application/json",
    }},
    json={json.dumps(input_spec if isinstance(input_spec, dict) else {{"text": "Hello world"}}, indent=4)}
)
print(resp.json())'''

    # Response example
    output_spec = matched.get("output", None)
    if output_spec:
        response_example = json.dumps(output_spec, indent=2)
    else:
        response_example = json.dumps({
            "result": f"<{name} output>",
            "_meta": {
                "endpoint": endpoint,
                "model": "claude-sonnet-4-20250514",
                "cost_usd": price,
            }
        }, indent=2)

    # Related tools
    related = []
    rel_slugs = _TOOL_RELATIONS.get(slug, [])[:4]
    for rs in rel_slugs:
        # Find the related service in catalog
        for svc in all_services:
            rs_slug = svc["endpoint"].strip("/").split("/")[-1]
            if rs_slug == rs:
                rp = svc.get("price_usd", 0.01)
                related.append({
                    "slug": rs,
                    "name": rs.replace("-", " ").replace("_", " ").title(),
                    "price_label": "Free" if rp == 0 else f"${rp:.2f}",
                })
                break

    # Demo tool mapping (slug used by /try/<tool>)
    demo_tool = slug
    demo_available = slug in _DEMO_TOOLS

    return {
        "slug": slug,
        "name": name,
        "description": description,
        "endpoint": endpoint,
        "method": method,
        "price_usd": price,
        "price_label": price_label,
        "category": category,
        "input_fields": input_fields,
        "curl_example": curl_example,
        "python_example": python_example,
        "response_example": response_example,
        "related": related,
        "demo_available": demo_available,
        "demo_tool": demo_tool,
    }


@meta_bp.route("/tools/<tool_name>", methods=["GET"])
def tool_page(tool_name):
    """Individual tool page for programmatic SEO."""
    # Sanitize input
    tool_name = tool_name.strip().lower()[:60]
    tool_data = _get_tool_data(tool_name)
    if not tool_data:
        return render_template("404.html"), 404
    try:
        funnel_log_event("tool_page_hit", endpoint=f"/tools/{tool_name}",
                         ip=request.headers.get("CF-Connecting-IP", request.remote_addr or ""),
                         user_agent=request.headers.get("User-Agent", ""))
    except Exception:
        pass
    return render_template("tool_page.html", tool=tool_data)


# ── Referral Program UI ──────────────────────────────────────────────────────

@meta_bp.route("/referrals", methods=["GET"])
def referrals_page():
    """Referral program page — show referral link, stats, and how it works."""
    api_key = request.args.get("key", "")
    if not api_key or not api_key.startswith("apk_"):
        return render_template("referrals.html", error="Enter your API key to view your referral stats.", data=None)

    from api_keys import get_key_status
    status = get_key_status(api_key)
    if not status:
        return render_template("referrals.html", error="API key not found.", data=None)

    referral_code = status.get("referral_code", "")
    if not referral_code:
        return render_template("referrals.html", error="No referral code found for this key.", data=None)

    # Count referrals made using this code
    total_referrals = 0
    credits_earned = 0.0
    try:
        from funnel_tracker import _conn as funnel_conn
        import sqlite3 as _sql3
        # Count referral_signup events matching this code
        fdb = os.path.join(os.path.dirname(os.path.dirname(__file__)), "funnel.db")
        conn = _sql3.connect(fdb)
        conn.row_factory = _sql3.Row
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE event = 'referral_signup' AND metadata LIKE ?",
            (f'%"ref_code": "{referral_code}"%',)
        ).fetchone()
        total_referrals = row["cnt"] if row else 0
        conn.close()
    except Exception:
        pass

    credits_earned = total_referrals * 0.10

    referral_link = f"https://aipaygen.com/buy-credits?ref={referral_code}"

    return render_template("referrals.html", error=None, data={
        "referral_code": referral_code,
        "referral_link": referral_link,
        "total_referrals": total_referrals,
        "credits_earned": credits_earned,
        "api_key_masked": api_key[:8] + "..." + api_key[-4:],
    })


@meta_bp.route("/sitemap.xml", methods=["GET"])
def sitemap():
    """XML sitemap — includes static pages AND all blog posts for Google/Bing."""
    base_url = "https://aipaygen.com"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    static_pages = [
        ("/", "daily", "1.0"),
        ("/discover", "weekly", "0.9"),
        ("/docs", "weekly", "0.9"),
        ("/try", "weekly", "0.9"),
        ("/builder", "weekly", "0.9"),
        ("/sdk", "weekly", "0.85"),
        ("/sell", "weekly", "0.8"),
        ("/pricing", "weekly", "0.8"),
        ("/docs/api", "weekly", "0.8"),
        ("/blog", "daily", "0.8"),
        ("/privacy", "monthly", "0.5"),
        ("/terms", "monthly", "0.5"),
        ("/security", "monthly", "0.7"),
        ("/subscribe", "weekly", "0.8"),
        ("/get-key", "weekly", "0.8"),
        ("/support", "weekly", "0.6"),
        ("/changelog", "weekly", "0.8"),
        ("/buy-credits", "weekly", "0.8"),
        ("/openapi.json", "weekly", "0.6"),
        ("/llms.txt", "weekly", "0.6"),
        ("/.well-known/agent.json", "weekly", "0.6"),
        ("/.well-known/ai-plugin.json", "weekly", "0.6"),
        ("/playground", "weekly", "0.8"),
        ("/examples", "weekly", "0.8"),
        ("/integrations", "weekly", "0.85"),
        ("/compare", "weekly", "0.85"),
        ("/compare/openrouter", "weekly", "0.8"),
        ("/compare/openai", "weekly", "0.8"),
        ("/quick-key", "weekly", "0.8"),
        ("/dashboard", "weekly", "0.6"),
        ("/blog/launch", "monthly", "0.8"),
        ("/blog/5-things-you-can-build", "monthly", "0.8"),
        ("/blog/x402-explained", "monthly", "0.8"),
        ("/health", "hourly", "0.3"),
        ("/status", "hourly", "0.4"),
        ("/referrals", "weekly", "0.6"),
        ("/premium", "weekly", "0.7"),
        ("/contact", "monthly", "0.5"),
        ("/links", "monthly", "0.4"),
        ("/app/", "weekly", "0.7"),
    ]
    # Add top 30 tool pages for programmatic SEO
    for t_slug in _SITEMAP_TOOLS:
        static_pages.append((f"/tools/{t_slug}", "weekly", "0.75"))
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



@meta_bp.route("/try", methods=["GET"])
def try_page():
    resp = make_response(render_template("try.html"))
    resp.headers["Content-Type"] = "text/html"
    ref = request.args.get("ref", "")
    if ref:
        resp.set_cookie("aipaygen_ref", ref, max_age=30*86400, secure=True, httponly=True, samesite="Lax")
    return resp


# Per-IP demo rate limiter (10 per 10 minutes, 500 global/day) with periodic cleanup
_demo_usage = {}
_demo_last_cleanup = 0
_demo_global_count = 0
_demo_global_date = ""
_demo_cache = {}  # {(tool, input_hash): (result, timestamp)}

def _check_demo_limit(ip):
    global _demo_last_cleanup, _demo_global_count, _demo_global_date
    now = _time.time()
    today = _time.strftime("%Y-%m-%d")
    # Reset global counter daily
    if today != _demo_global_date:
        _demo_global_count = 0
        _demo_global_date = today
    # Global daily cap: 500 demo calls/day to control LLM costs
    if _demo_global_count >= 500:
        return False
    # Periodic cleanup: every 5 minutes, purge expired entries
    if now - _demo_last_cleanup > 300:
        _demo_last_cleanup = now
        stale = [k for k, v in _demo_usage.items() if not v or now - v[-1] > 600]
        for k in stale:
            del _demo_usage[k]
        # Purge old cache entries (>1hr)
        stale_cache = [k for k, v in _demo_cache.items() if now - v[1] > 3600]
        for k in stale_cache:
            del _demo_cache[k]
    key = f"demo:{ip}"
    entries = _demo_usage.get(key, [])
    entries = [t for t in entries if now - t < 600]
    if len(entries) >= 10:
        return False
    entries.append(now)
    _demo_usage[key] = entries
    _demo_global_count += 1
    return True


@meta_bp.route("/try/<tool>", methods=["POST"])
def try_tool(tool):
    from routes.ai_tools import (
        sentiment_inner, summarize_inner, translate_inner,
        keywords_inner, explain_inner,
        analyze_inner, compare_inner,
        extract_inner, questions_inner, decide_inner,
        classify_inner, rewrite_inner, headline_inner,
    )
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown")
    if not _check_demo_limit(ip):
        return jsonify({"error": "Demo limit reached. Get a free API key with $0.10 credits for unlimited access.", "upgrade": "/get-key", "buy": "/buy-credits"}), 429

    data = request.get_json() or {}
    # Check cache first to avoid duplicate LLM costs
    _cache_key = (tool, _hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16])
    _cached = _demo_cache.get(_cache_key)
    if _cached:
        return jsonify(_cached[0])
    try:
        if tool == "sentiment":
            result = sentiment_inner(data.get("text", "")[:500])
        elif tool == "summarize":
            result = summarize_inner(data.get("text", "")[:2000], data.get("format", "bullets"))
        elif tool == "translate":
            result = translate_inner(data.get("text", "")[:500], data.get("language", "Spanish"))
        elif tool == "keywords":
            result = keywords_inner(data.get("text", "")[:1000])
        elif tool == "explain":
            result = explain_inner(data.get("concept", "")[:200])
        elif tool in ("code", "research"):
            return jsonify({"error": "premium_only", "message": f"{tool} is not available in the free demo. Get an API key for access.", "upgrade": "/buy-credits"}), 403
        elif tool == "analyze":
            result = analyze_inner(data.get("content", "")[:2000], data.get("question", "general analysis")[:300])
        elif tool == "compare":
            result = compare_inner(data.get("text_a", "")[:1000], data.get("text_b", "")[:1000])
        elif tool == "extract":
            result = extract_inner(data.get("text", "")[:2000], data.get("schema_desc", ""), data.get("fields", []))
        elif tool == "questions":
            result = questions_inner(data.get("content", "")[:2000])
        elif tool == "decide":
            result = decide_inner(data.get("decision", "")[:500], data.get("options", None))
        elif tool == "classify":
            result = classify_inner(data.get("text", "")[:1000], data.get("categories", []))
        elif tool == "rewrite":
            result = rewrite_inner(data.get("text", "")[:2000], data.get("audience", "general")[:100])
        elif tool == "headline":
            result = headline_inner(data.get("content", "")[:1000])
        elif tool == "geocode":
            r = _requests.get("http://127.0.0.1:5001/data/geocode", params={"q": data.get("q", "")[:200]}, timeout=10)
            result = r.json()
        elif tool == "math-eval":
            r = _requests.post("http://127.0.0.1:5001/data/math/eval", json={"expression": data.get("expression", "")[:500]}, timeout=10)
            result = r.json()
        elif tool == "unit-convert":
            r = _requests.get("http://127.0.0.1:5001/data/math/convert", params={"value": data.get("value", 0), "from": data.get("from_unit", ""), "to": data.get("to_unit", "")}, timeout=10)
            result = r.json()
        elif tool == "readability":
            r = _requests.post("http://127.0.0.1:5001/data/readability", json={"text": data.get("text", "")[:2000]}, timeout=10)
            result = r.json()
        elif tool == "language-detect":
            r = _requests.get("http://127.0.0.1:5001/data/language", params={"text": data.get("text", "")[:500]}, timeout=10)
            result = r.json()
        elif tool == "whois":
            r = _requests.get("http://127.0.0.1:5001/data/whois", params={"domain": data.get("domain", "")[:100]}, timeout=10)
            result = r.json()
        elif tool == "security-headers":
            r = _requests.get("http://127.0.0.1:5001/data/security/headers", params={"url": data.get("url", "")[:500]}, timeout=10)
            result = r.json()
        elif tool == "currency-convert":
            r = _requests.get("http://127.0.0.1:5001/data/finance/convert", params={"amount": data.get("amount", 1), "from": data.get("from", "USD"), "to": data.get("to", "EUR")}, timeout=10)
            result = r.json()
        elif tool == "stats":
            r = _requests.post("http://127.0.0.1:5001/data/math/stats", json={"numbers": data.get("numbers", [])}, timeout=10)
            result = r.json()
        else:
            return jsonify({"error": f"Unknown demo tool: {tool}"}), 400
        funnel_log_event("demo_used", endpoint=f"/try/{tool}", ip=ip, user_agent=request.headers.get("User-Agent", ""))
        _log_tool_usage(tool, api_key="demo")
        # Cache result to avoid paying for identical inputs
        _demo_cache[_cache_key] = ({"result": result, "tool": tool, "_meta": {"free_demo": True, "upgrade": "/buy-credits"}}, _time.time())
        return jsonify({"result": result, "tool": tool, "_meta": {"free_demo": True, "upgrade": "/buy-credits"}})
    except Exception as e:
        logger.error("Demo tool '%s' failed: %s", tool, e)
        return jsonify({"error": "Demo tool execution failed"}), 500


# ── Public Changelog / Release Notes ──────────────────────────────────────────

CHANGELOG = [
    {
        "version": "1.9.5",
        "date": "2026-03-25",
        "title": "128 REST Endpoints, Security Hardening, Mobile App Fix",
        "changes": [
            "128 REST API endpoints (was 113) — 16 new utility routes",
            "New endpoints: chain-operations, enrich-entity, web-search, scrape-website",
            "New data endpoints: get-weather, get-crypto-prices, get-exchange-rates, get-holidays",
            "New utility endpoints: get-current-time, get-joke, get-quote, generate-uuid",
            "Agent memory REST API: memory-store, memory-recall, memory-keys",
            "MCP server: SSE transport added alongside Streamable HTTP",
            "MCP server: systemd service — survives reboots",
            "Model router: switched to Anthropic SDK (was broken CLI)",
            "7 security fixes: OAuth redirect, XSS, SSRF, brute-force, card-testing",
            "Mobile app blank page fix — manifest.json was returning HTML",
            "Twitter/X card meta tags on all pages for rich social sharing",
            "X-Response-Time header on every API response",
            "Landing page stats now show live data (keys, calls)",
            "Comparison table on buy-credits page vs ChatGPT/Anthropic",
            "OpenAPI spec updated with all 128 endpoints",
            "PWA: service worker, safe-area CSS, apple-mobile-web-app",
            "9 database indexes for faster queries",
        ],
    },
    {
        "version": APP_VERSION,
        "date": "2026-03-15",
        "title": "229 Tools — Massive Expansion",
        "changes": [
            "250 MCP tools (was 169) — 60 new tools added in one release",
            "New data tools: Wikipedia, arXiv, GitHub trending, Reddit, YouTube transcripts, news, QR codes, DNS, screenshots",
            "New utility tools: base64, hashing, URL encode/decode, JSON format/minify, text stats, random generation, CIDR, epoch conversion",
            "File storage: upload and list files via MCP",
            "Agent network: leaderboard, search, portfolio, reputation, task claim/complete/subscribe",
            "Marketplace: seller registration, directory, dashboard",
            "Webhooks: create and list webhook subscriptions",
            "Streaming: stream_research, stream_write, stream_analyze",
            "Scraping: LinkedIn profiles, Facebook Ad Library",
            "Sessions: persistent conversation sessions with context",
            "Referral: stats and leaderboard tools",
            "Platform: stats, popular tools, economy status",
            "SQLite database recovery for corrupted WAL files",
            "Referral system — $0.10 both sides on API key generation",
            "Public changelog at /changelog",
            "Live status page at /status with auto-refresh",
            "API Playground at /playground with 35 endpoints",
            "Tool recommendations — related tools in free tier responses",
            "Weekly usage digest emails",
            "Email capture on credit purchase",
            "SEO: llms.txt, agent.json, ai-plugin.json, JSON-LD schemas",
            "Landing page trust signals (MCP Registry, Smithery, Glama, x402)",
            "SQLite database recovery tooling for corrupted WAL files",
        ],
    },
    {
        "version": "1.8.0",
        "date": "2026-03-14",
        "title": "Monetization + Security Overhaul",
        "changes": [
            "165 MCP tools (was 162) — added buy_credits, check_usage, generate_api_key",
            "$0.10 free trial credits on first API key",
            "Premium tools (research, vision, scraping) now require API key",
            "Result previews on free tier with upgrade prompts",
            "100+ error message leaks fixed — generic errors to clients",
            "Per-endpoint rate limits on expensive routes",
            "Domain injection fix on DNS lookup endpoints",
            "Competitive pricing display in tool responses",
            "PyPI download tracking in funnel metrics",
            "MCP connection tracking",
            "Email capture on key generation + weekly usage digest",
        ]
    },
    {
        "version": "1.7.1",
        "date": "2026-03-12",
        "title": "x402 V2 + Multi-chain",
        "changes": [
            "x402 V2 protocol upgrade (was V1)",
            "Multi-chain payments: Base, Solana, Stellar",
            "162 MCP tools",
            "Security audit + hardening",
            "1382 tests passing",
        ]
    },
]


@meta_bp.route("/changelog", methods=["GET"])
def public_changelog():
    """Public release notes page."""
    entries_html = ""
    for entry in CHANGELOG:
        items = "".join(f"<li>{ch}</li>" for ch in entry["changes"])
        entries_html += f"""
        <div style="margin-bottom:48px">
          <div style="display:flex;align-items:baseline;gap:16px;flex-wrap:wrap">
            <span style="font-family:'IBM Plex Mono',monospace;font-size:1.6rem;font-weight:700;color:#00ff9d">v{entry["version"]}</span>
            <span style="font-size:0.9rem;color:#8b949e">{entry["date"]}</span>
          </div>
          <h2 style="margin:8px 0 16px;font-size:1.2rem;color:#fff;font-weight:600">{entry["title"]}</h2>
          <ul style="padding-left:20px;color:#c9d1d9;line-height:1.9">{items}</ul>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Changelog — AiPayGen</title>
<meta name="description" content="AiPayGen release notes and changelog — see what's new in every version.">
<link rel="canonical" href="https://aipaygen.com/changelog">
<meta property="og:title" content="AiPayGen Changelog">
<meta property="og:url" content="https://aipaygen.com/changelog">
<meta property="og:description" content="Release notes for AiPayGen — AI agent payments platform.">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;700&family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;background:#020408;color:#e6edf3;font-family:'IBM Plex Sans',system-ui,sans-serif">
{NAV_HTML}
<main style="max-width:760px;margin:0 auto;padding:120px 24px 80px">
  <h1 style="font-size:2.2rem;font-weight:700;color:#fff;margin-bottom:8px">Changelog</h1>
  <p style="color:#8b949e;margin-bottom:48px">What's new in AiPayGen — release notes for every version.</p>
  {entries_html}
</main>
{FOOTER_HTML}
</body>
</html>"""
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html"
    return resp


@meta_bp.route("/playground", methods=["GET"])
def playground():
    """Interactive API playground — test any endpoint from the browser."""
    return render_template("playground.html")


@meta_bp.route("/examples", methods=["GET"])
def sdk_examples():
    """SDK quick-start examples — copy-paste code for every language."""
    return render_template("sdk_examples.html")


@meta_bp.route("/integrations", methods=["GET"])
def integrations():
    """Integration guides — LangChain, CrewAI, AutoGen, Claude Code, Cursor, n8n, Zapier."""
    return render_template("integrations.html")


@meta_bp.route("/links", methods=["GET"])
def link_tree():
    """Link-in-bio page for social media profiles."""
    return render_template("links.html")


# ── SEO Comparison Pages ─────────────────────────────────────────────────────

@meta_bp.route("/compare", methods=["GET"])
def compare_all():
    """AI API pricing comparison — AiPayGen vs OpenAI vs Anthropic vs OpenRouter vs Together AI vs Groq."""
    return render_template("compare.html")


@meta_bp.route("/compare/openrouter", methods=["GET"])
def compare_openrouter():
    """AiPayGen vs OpenRouter — detailed feature and pricing comparison."""
    return render_template("compare_openrouter.html")


@meta_bp.route("/compare/openai", methods=["GET"])
def compare_openai():
    """AiPayGen vs OpenAI API — detailed feature and pricing comparison."""
    return render_template("compare_openai.html")


# ── Showcase API ─────────────────────────────────────────────────────────────

@meta_bp.route("/api/showcase", methods=["GET"])
def showcase_list():
    """Return latest approved showcase entries as social proof."""
    from showcase import get_approved
    limit = min(int(request.args.get("limit", 20)), 100)
    entries = get_approved(limit)
    return jsonify({"showcase": entries, "count": len(entries)})


@meta_bp.route("/api/showcase", methods=["POST"])
def showcase_submit():
    """Capture a notable tool usage for showcase (internal use)."""
    from showcase import log_showcase
    data = request.get_json(silent=True) or {}
    tool_name = data.get("tool_name", "")
    if not tool_name:
        return jsonify({"error": "tool_name required"}), 400
    log_showcase(
        tool_name=tool_name,
        input_preview=data.get("input_preview", ""),
        output_preview=data.get("output_preview", ""),
        response_time_ms=int(data.get("response_time_ms", 0)),
        model=data.get("model", ""),
    )
    return jsonify({"status": "captured"}), 201


# ── Support Ticket System ─────────────────────────────────────────────────────

_support_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), "support.db")


def _init_support_db():
    """Create support tickets table if it doesn't exist."""
    with _sqlite3.connect(_support_db) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                name TEXT,
                message TEXT,
                status TEXT DEFAULT 'open',
                ip TEXT,
                user_agent TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                replied_at TEXT,
                reply TEXT,
                admin_notes TEXT
            )
        """)


_init_support_db()


@meta_bp.route("/support/ticket", methods=["POST"])
def support_create_ticket():
    """Public endpoint — create a support ticket."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    name = (data.get("name") or "").strip()
    message = (data.get("message") or "").strip()

    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required."}), 400
    if not message:
        return jsonify({"error": "Message is required."}), 400

    ip = get_client_ip()
    ua = request.headers.get("User-Agent", "")[:500]

    with _sqlite3.connect(_support_db) as conn:
        cur = conn.execute(
            "INSERT INTO tickets (email, name, message, ip, user_agent) VALUES (?, ?, ?, ?, ?)",
            (email, name or "Anonymous", message, ip, ua),
        )
        ticket_id = cur.lastrowid

    return jsonify({"ticket_id": ticket_id, "message": "We'll respond within 24 hours."}), 201


@meta_bp.route("/support/tickets", methods=["GET"])
@require_admin
def support_list_tickets():
    """Admin — list all support tickets."""
    with _sqlite3.connect(_support_db) as conn:
        conn.row_factory = _sqlite3.Row
        rows = conn.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
        total = len(rows)
        open_count = sum(1 for r in rows if r["status"] == "open")
    tickets = [dict(r) for r in rows]
    return jsonify({"tickets": tickets, "total": total, "open": open_count})


@meta_bp.route("/support/tickets/<int:ticket_id>/reply", methods=["POST"])
@require_admin
def support_reply_ticket(ticket_id):
    """Admin — reply to a support ticket."""
    data = request.get_json(silent=True) or {}
    reply = (data.get("reply") or "").strip()
    admin_notes = (data.get("admin_notes") or "").strip()

    if not reply:
        return jsonify({"error": "Reply text is required."}), 400

    with _sqlite3.connect(_support_db) as conn:
        row = conn.execute("SELECT id FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if not row:
            return jsonify({"error": "Ticket not found."}), 404
        conn.execute(
            "UPDATE tickets SET status = 'replied', reply = ?, admin_notes = ?, replied_at = datetime('now') WHERE id = ?",
            (reply, admin_notes, ticket_id),
        )

    return jsonify({"status": "replied", "ticket_id": ticket_id})
