"""Blueprint for x402 discovery, analytics, and revenue estimation.
Inspired by APIToll's discovery API and x402 protocol standards."""

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

from flask import Blueprint, request, jsonify

from helpers import agent_response

discovery_bp = Blueprint("discovery", __name__)

# Category mapping for our paid endpoints
_CATEGORIES = {
    "ai": {
        "description": "AI-powered content generation and analysis",
        "routes": [
            "/research", "/write", "/analyze", "/code", "/summarize", "/translate",
            "/social", "/chat", "/plan", "/decide", "/proofread", "/explain",
            "/questions", "/outline", "/email", "/pitch", "/debate", "/headline",
            "/rewrite", "/workflow", "/review-code", "/generate-docs", "/convert-code",
            "/generate-api-spec", "/diff", "/changelog", "/name-generator", "/think",
            "/vision", "/rag", "/diagram", "/json-schema", "/test-cases",
        ],
    },
    "data": {
        "description": "Web scraping, search, and data extraction",
        "routes": [
            "/scrape", "/search", "/extract", "/qa", "/classify", "/sentiment",
            "/keywords", "/compare", "/transform", "/score", "/timeline", "/action",
            "/fact", "/tag", "/parse-csv", "/privacy-check",
            "/scrape/google-maps", "/scrape/instagram", "/scrape/tweets",
            "/scrape/linkedin", "/scrape/youtube", "/scrape/web", "/scrape/tiktok",
            "/scrape/facebook-ads", "/scrape/actor", "/web/search", "/enrich",
        ],
    },
    "agent": {
        "description": "Agent infrastructure — memory, messaging, tasks, knowledge",
        "routes": [
            "/memory/set", "/memory/get", "/memory/search", "/memory/list",
            "/memory/clear", "/message/send", "/message/broadcast", "/message/reply",
            "/knowledge/add", "/task/submit", "/task/complete", "/code/run",
            "/marketplace/call",
        ],
    },
    "utility": {
        "description": "Developer utilities — regex, cron, mock data, batch ops, math, transforms",
        "routes": [
            "/batch", "/pipeline", "/chain", "/api-call", "/sql", "/regex",
            "/mock", "/cron",
            "/data/jwt/decode", "/data/markdown", "/data/placeholder", "/data/avatar",
            "/data/transform/json-to-csv", "/data/transform/xml", "/data/transform/yaml",
            "/data/math/eval", "/data/math/convert", "/data/math/stats",
            "/data/datetime/between", "/data/datetime/business-days", "/data/datetime/unix",
        ],
    },
    "web_analysis": {
        "description": "Web scraping, domain analysis, and security tools",
        "routes": [
            "/data/meta", "/data/links", "/data/sitemap", "/data/robots",
            "/data/headers", "/data/ssl", "/data/favicon", "/data/whois",
            "/data/domain", "/data/ens", "/data/enrich/domain", "/data/enrich/github",
            "/data/security/headers", "/data/security/techstack", "/data/security/uptime",
        ],
    },
    "nlp": {
        "description": "Natural language processing — readability, language detection, entities",
        "routes": [
            "/data/readability", "/data/language", "/data/profanity",
            "/data/entities", "/data/similarity", "/data/extract/text", "/data/extract/pdf",
        ],
    },
    "finance": {
        "description": "Financial data — stocks, forex, currency conversion, crypto",
        "routes": [
            "/data/finance/history", "/data/finance/forex", "/data/finance/convert",
            "/data/crypto/trending",
        ],
    },
    "location": {
        "description": "Geocoding, company search, and location services",
        "routes": [
            "/data/geocode", "/data/geocode/reverse", "/data/company",
        ],
    },
    "commerce": {
        "description": "Payments, wallets, sessions, and workflows",
        "routes": [
            "/credits/buy", "/session/start", "/workflow/run",
        ],
    },
}

PLATFORM_FEE = 0.03

# Set at registration time by app.py to avoid circular imports
_routes_ref = {}


def init_discovery(routes_dict):
    """Called from app.py to inject the routes dict."""
    global _routes_ref
    _routes_ref = routes_dict


def _get_routes_dict():
    """Return the routes dict injected at init time."""
    return _routes_ref


def _categorize_route(path):
    """Return the category for a route path."""
    for cat, info in _CATEGORIES.items():
        if path in info["routes"]:
            return cat
    return "other"


def _parse_price(price_str):
    """Extract numeric price from '$0.01' format."""
    if not price_str:
        return 0.0
    m = re.search(r'[\d.]+', str(price_str))
    return float(m.group()) if m else 0.0


# ── Discovery Endpoints ──────────────────────────────────────────────────────


@discovery_bp.route("/discover", methods=["GET"])
def discover():
    """Machine-readable endpoint catalog with pricing, categories, and search."""
    routes = _get_routes_dict()
    if not routes:
        return jsonify({"error": "routes not loaded"}), 500

    # Query params
    category = request.args.get("category")
    search = request.args.get("search", "").lower()
    chain = request.args.get("chain")
    min_price = float(request.args.get("min_price", 0))
    max_price = float(request.args.get("max_price", 999))
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 100)

    endpoints = []
    for route_key, cfg in routes.items():
        parts = route_key.split(" ", 1)
        method = parts[0]
        path = parts[1] if len(parts) > 1 else route_key

        price = _parse_price(cfg.accepts[0].price) if cfg.accepts else 0
        network = cfg.accepts[0].network if cfg.accepts else ""
        desc = cfg.description or ""
        cat = _categorize_route(path)

        # Filters
        if category and cat != category:
            continue
        if search and search not in desc.lower() and search not in path.lower():
            continue
        if chain and chain.lower() not in str(network).lower():
            continue
        if price < min_price or price > max_price:
            continue

        endpoints.append({
            "method": method,
            "path": path,
            "price_usd": price,
            "chain": str(network),
            "currency": "USDC",
            "description": desc,
            "category": cat,
            "url": f"https://api.aipaygen.com{path}",
        })

    # Sort by category then price
    endpoints.sort(key=lambda e: (e["category"], e["price_usd"]))

    total = len(endpoints)
    start = (page - 1) * per_page
    paginated = endpoints[start:start + per_page]

    # Category summary
    cat_counts = {}
    for e in endpoints:
        cat_counts[e["category"]] = cat_counts.get(e["category"], 0) + 1

    return jsonify({
        "endpoints": paginated,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
        "categories": {k: {"count": v, "description": _CATEGORIES.get(k, {}).get("description", "")}
                       for k, v in cat_counts.items()},
        "protocol": "x402",
        "chains": ["eip155:8453"],
        "currency": "USDC",
        "facilitator": "https://api.cdp.coinbase.com/platform/v2/x402",
        "_meta": {
            "ts": datetime.utcnow().isoformat() + "Z",
            "hint": "Use ?category=ai&search=code to filter. All endpoints accept x402 USDC payments.",
        },
    })


@discovery_bp.route("/discover/pricing", methods=["GET"])
def discover_pricing():
    """Pricing overview — min/max/avg, histogram, endpoint count."""
    routes = _get_routes_dict()
    prices = [_parse_price(cfg.accepts[0].price) for cfg in routes.values() if cfg.accepts]

    if not prices:
        return jsonify({"error": "no priced endpoints"}), 500

    # Price histogram
    buckets = {"$0.001-$0.01": 0, "$0.01-$0.02": 0, "$0.02-$0.05": 0, "$0.05-$0.10": 0, "$0.10+": 0}
    for p in prices:
        if p <= 0.01:
            buckets["$0.001-$0.01"] += 1
        elif p <= 0.02:
            buckets["$0.01-$0.02"] += 1
        elif p <= 0.05:
            buckets["$0.02-$0.05"] += 1
        elif p <= 0.10:
            buckets["$0.05-$0.10"] += 1
        else:
            buckets["$0.10+"] += 1

    return jsonify({
        "total_endpoints": len(prices),
        "min_price_usd": min(prices),
        "max_price_usd": max(prices),
        "avg_price_usd": round(sum(prices) / len(prices), 4),
        "median_price_usd": sorted(prices)[len(prices) // 2],
        "histogram": buckets,
        "platform_fee": f"{PLATFORM_FEE * 100}%",
        "currency": "USDC",
        "chains": ["eip155:8453 (Base Mainnet)"],
    })


@discovery_bp.route("/sell/estimate", methods=["POST", "GET"])
def sell_estimate():
    """Revenue estimator — what sellers could earn."""
    if request.method == "POST":
        data = request.get_json() or {}
    else:
        data = dict(request.args)

    price_per_call = float(data.get("price_per_call", 0.005))
    daily_calls = int(data.get("daily_calls", 1000))

    if price_per_call <= 0 or daily_calls <= 0:
        return jsonify({"error": "price_per_call and daily_calls must be positive"}), 400

    gross_daily = price_per_call * daily_calls
    net_daily = gross_daily * (1 - PLATFORM_FEE)
    net_monthly = net_daily * 30
    net_annual = net_daily * 365

    return jsonify({
        "input": {
            "price_per_call_usd": price_per_call,
            "daily_calls": daily_calls,
        },
        "revenue": {
            "daily_gross_usd": round(gross_daily, 2),
            "daily_net_usd": round(net_daily, 2),
            "monthly_net_usd": round(net_monthly, 2),
            "annual_net_usd": round(net_annual, 2),
        },
        "platform_fee": f"{PLATFORM_FEE * 100}%",
        "note": "You keep 97% of every payment. Instant USDC settlement on Base.",
        "get_started": "POST /sell/register to list your API",
    })


@discovery_bp.route("/wallet/analytics", methods=["GET"])
def wallet_analytics():
    """Wallet spend analytics — spend breakdown, daily trend, success rate."""
    wallet_id = request.headers.get("X-Wallet-ID") or request.args.get("wallet_id")
    if not wallet_id:
        return jsonify({"error": "X-Wallet-ID header or wallet_id param required"}), 400

    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "seller_marketplace.db")
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        return jsonify({"error": "database unavailable"}), 500

    try:
        # Total spend
        row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(amount_usd), 0) as total FROM wallet_transactions WHERE wallet_id=?",
            (wallet_id,)
        ).fetchone()
        total_txns = row["cnt"]
        total_spent = row["total"]

        # Spend by seller (top 10)
        seller_rows = conn.execute(
            "SELECT seller_slug, COUNT(*) as calls, SUM(amount_usd) as spent "
            "FROM wallet_transactions WHERE wallet_id=? AND seller_slug != '' "
            "GROUP BY seller_slug ORDER BY spent DESC LIMIT 10",
            (wallet_id,)
        ).fetchall()
        by_seller = [{"seller": r["seller_slug"], "calls": r["calls"], "spent_usd": round(r["spent"], 4)} for r in seller_rows]

        # Spend by day (last 30 days)
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        daily_rows = conn.execute(
            "SELECT DATE(created_at) as day, COUNT(*) as calls, SUM(amount_usd) as spent "
            "FROM wallet_transactions WHERE wallet_id=? AND created_at >= ? "
            "GROUP BY DATE(created_at) ORDER BY day DESC",
            (wallet_id, thirty_days_ago)
        ).fetchall()
        by_day = [{"date": r["day"], "calls": r["calls"], "spent_usd": round(r["spent"], 4)} for r in daily_rows]

        # Wallet info
        wallet_row = conn.execute("SELECT * FROM agent_wallets WHERE id=?", (wallet_id,)).fetchone()
        wallet_info = dict(wallet_row) if wallet_row else {}

        return jsonify({
            "wallet_id": wallet_id,
            "balance_usd": wallet_info.get("balance_usd", 0),
            "total_transactions": total_txns,
            "total_spent_usd": round(total_spent, 4),
            "avg_per_call_usd": round(total_spent / total_txns, 4) if total_txns > 0 else 0,
            "spend_by_seller": by_seller,
            "spend_by_day": by_day,
            "budget": {
                "daily_budget_usd": wallet_info.get("daily_budget", 10),
                "monthly_budget_usd": wallet_info.get("monthly_budget", 100),
                "spent_today_usd": wallet_info.get("spent_today", 0),
                "spent_month_usd": wallet_info.get("spent_month", 0),
            },
            "_meta": {"ts": datetime.utcnow().isoformat() + "Z"},
        })
    finally:
        conn.close()


@discovery_bp.route("/discover/openapi", methods=["GET"])
def discover_openapi():
    """Simplified OpenAPI-compatible spec with x402 pricing extensions."""
    routes = _get_routes_dict()
    paths = {}

    for route_key, cfg in routes.items():
        parts = route_key.split(" ", 1)
        method = parts[0].lower()
        path = parts[1] if len(parts) > 1 else route_key
        price = _parse_price(cfg.accepts[0].price) if cfg.accepts else 0
        network = str(cfg.accepts[0].network) if cfg.accepts else ""

        if path not in paths:
            paths[path] = {}
        paths[path][method] = {
            "summary": cfg.description or "",
            "x-402-price": price,
            "x-402-currency": "USDC",
            "x-402-network": network,
            "x-402-pay-to": "0x366D488a48de1B2773F3a21F1A6972715056Cb30",
            "responses": {
                "200": {"description": "Success"},
                "402": {"description": f"Payment Required — ${price} USDC"},
            },
        }

    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "AiPayGen API",
            "description": "155 AI tools with x402 USDC micropayments on Base Mainnet",
            "version": "2.0.0",
            "x-402-protocol": True,
            "contact": {"url": "https://aipaygen.com"},
        },
        "servers": [{"url": "https://api.aipaygen.com"}],
        "x-402": {
            "chains": ["eip155:8453"],
            "currency": "USDC",
            "facilitator": "https://api.cdp.coinbase.com/platform/v2/x402",
            "wallet": "0x366D488a48de1B2773F3a21F1A6972715056Cb30",
        },
        "paths": paths,
    }
    return jsonify(spec)


@discovery_bp.route("/.well-known/x402", methods=["GET"])
def well_known_x402():
    """x402 protocol discovery metadata."""
    routes = _get_routes_dict()
    prices = [_parse_price(cfg.accepts[0].price) for cfg in routes.values() if cfg.accepts]

    return jsonify({
        "protocol": "x402",
        "version": "2.0",
        "chains": [
            {
                "network": "eip155:8453",
                "name": "Base Mainnet",
                "currency": "USDC",
                "contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "settlement_time": "~2s",
            },
            {
                "network": "solana:mainnet",
                "name": "Solana Mainnet",
                "currency": "USDC",
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "settlement_time": "~400ms",
            },
        ],
        "wallet": "0x366D488a48de1B2773F3a21F1A6972715056Cb30",
        "facilitator": "https://api.cdp.coinbase.com/platform/v2/x402",
        "payment_scheme": "exact",
        "pricing": {
            "currency": "USDC",
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
            "total_endpoints": len(prices),
        },
        "discovery_endpoints": {
            "catalog": "https://api.aipaygen.com/discover",
            "pricing": "https://api.aipaygen.com/discover/pricing",
            "openapi": "https://api.aipaygen.com/discover/openapi",
            "ai_plugin": "https://api.aipaygen.com/.well-known/ai-plugin.json",
        },
        "seller_marketplace": {
            "register": "POST https://api.aipaygen.com/sell/register",
            "directory": "GET https://api.aipaygen.com/sell/directory",
            "estimate": "POST https://api.aipaygen.com/sell/estimate",
        },
        "buyer": {
            "create_wallet": "POST https://api.aipaygen.com/wallet/create",
            "fund_wallet": "POST https://api.aipaygen.com/wallet/fund",
            "analytics": "GET https://api.aipaygen.com/wallet/analytics",
        },
        "_meta": {
            "ts": datetime.utcnow().isoformat() + "Z",
            "docs": "https://aipaygen.com/docs",
        },
    })


@discovery_bp.route("/discover/compare", methods=["GET"])
def discover_compare():
    """Compare AiPayGen with competitors — for agent decision-making."""
    return jsonify({
        "comparison": [
            {
                "platform": "AiPayGen",
                "endpoints": "155",
                "protocol": "x402",
                "chains": ["Base"],
                "settlement": "~2s",
                "min_price": "$0.001",
                "platform_fee": "3%",
                "free_tier": "10 calls/day",
                "mcp_tools": 153,
                "agent_builder": True,
                "seller_marketplace": True,
                "url": "https://api.aipaygen.com",
            },
            {
                "platform": "APIToll",
                "endpoints": "75",
                "protocol": "x402",
                "chains": ["Base", "Solana"],
                "settlement": "~400ms (Solana), ~2s (Base)",
                "min_price": "$0.001",
                "platform_fee": "3%",
                "free_tier": "10,000 calls/day",
                "url": "https://apitoll.com",
            },
            {
                "platform": "RelAI",
                "endpoints": "varies",
                "protocol": "x402",
                "chains": ["Solana", "Base", "Avalanche", "Ethereum", "Polygon"],
                "settlement": "varies",
                "url": "https://relai.fi",
            },
        ],
        "our_advantages": [
            "155 AI-powered tools (not just proxies)",
            "Agent builder with scheduling",
            "MCP server with 155 tools",
            "Seller marketplace with escrow",
            "Agent memory, messaging, and task systems",
            "Multi-step workflows and pipelines",
        ],
    })
