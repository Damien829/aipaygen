import json
import uuid
import threading
import requests as _requests
from datetime import datetime
from flask import Blueprint, request, jsonify

from agent_memory import (
    marketplace_list_service, marketplace_get_services,
    marketplace_get_service, marketplace_increment_calls,
    marketplace_deregister,
)
from api_catalog import get_all_apis, get_api, get_recent_runs
from apify_client import run_actor_sync
from api_discovery import run_all_hunters
from helpers import log_payment, agent_response, get_client_ip as _get_client_ip, call_llm, require_admin
from funnel_tracker import log_event as funnel_log_event

marketplace_bp = Blueprint("marketplace", __name__)

_claude = None
_discovery_jobs = {}


def init_marketplace_bp(claude_client, discovery_jobs):
    global _claude, _discovery_jobs
    _claude = claude_client
    _discovery_jobs = discovery_jobs


# ── Catalog & Discovery ─────────────────────────────────────────────


@marketplace_bp.route("/catalog", methods=["GET"])
def catalog():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    category = request.args.get("category")
    source = request.args.get("source")
    min_score = request.args.get("min_score", type=float)
    free_only = request.args.get("free_only", "").lower() in ("1", "true", "yes")
    apis, total = get_all_apis(page=page, per_page=per_page, category=category,
                               source=source, min_score=min_score, free_only=free_only)
    try:
        funnel_log_event("catalog_browse", _get_client_ip())
    except Exception:
        pass
    return jsonify({
        "apis": apis,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "_meta": {"endpoint": "/catalog", "ts": datetime.utcnow().isoformat() + "Z",
                  "hint": "Use POST /api-call with api_id to call any API"},
    })


@marketplace_bp.route("/catalog/<int:api_id>", methods=["GET"])
def catalog_item(api_id):
    api = get_api(api_id)
    if not api:
        return jsonify({"error": "not_found"}), 404
    return jsonify(api)


@marketplace_bp.route("/run-discovery", methods=["POST"])
@require_admin
def run_discovery():
    job_id = str(uuid.uuid4())[:8]
    _discovery_jobs[job_id] = {"status": "running", "started_at": datetime.utcnow().isoformat()}

    def _run():
        try:
            results = run_all_hunters(_claude)
            _discovery_jobs[job_id].update({"status": "completed", "results": results})
        except Exception as e:
            _discovery_jobs[job_id].update({"status": "error", "error": str(e)})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "status": "running",
                    "check": f"/discovery-status/{job_id}"})


@marketplace_bp.route("/discovery-status/<job_id>", methods=["GET"])
def discovery_status(job_id):
    job = _discovery_jobs.get(job_id)
    if not job:
        return jsonify({"error": "job_not_found", "hint": "POST /run-discovery to start a new job"}), 404
    return jsonify({"job_id": job_id, **job, "recent_runs": get_recent_runs(5)})


@marketplace_bp.route("/api-call", methods=["POST"])
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
    # SSRF protection — validate constructed URL
    from security import validate_url, SSRFError
    try:
        validate_url(url, allow_http=False)
    except SSRFError as e:
        return jsonify({"error": f"Blocked URL: {e}"}), 403
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = _requests.get(url, params=params, headers=headers, timeout=15)
        result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        enrichment = None
        if enrich and isinstance(result, (dict, list)):
            llm_result, llm_err = call_llm(
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


# ── Scrape (Apify) Routes ───────────────────────────────────────────


@marketplace_bp.route("/scrape/google-maps", methods=["POST"])
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


@marketplace_bp.route("/scrape/instagram", methods=["POST"])
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


@marketplace_bp.route("/scrape/tweets", methods=["POST"])
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


@marketplace_bp.route("/scrape/linkedin", methods=["POST"])
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


@marketplace_bp.route("/scrape/youtube", methods=["POST"])
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


@marketplace_bp.route("/scrape/web", methods=["POST"])
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


@marketplace_bp.route("/scrape/tiktok", methods=["POST"])
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


@marketplace_bp.route("/scrape/facebook-ads", methods=["POST"])
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


_ALLOWED_ACTORS = {
    "nwua9Gu5YrADL7ZDj",  # Instagram
    "shu8hvrXbJbY3Eb9W",  # TikTok
    "61RPP7dywgiy0JPD0",  # YouTube
    "2SyF0bVxmgGr8IVCZ",  # Google Maps
    "h7sDV53CddomktSi5",  # Twitter/X
    "aYG0l9s7dbB7j3gbS",  # Web scraper
    "GdWCkxBtKWOsKjdch",  # Google search
    "JJghSZmShuco4j9gJ",  # Facebook ads
}


@marketplace_bp.route("/scrape/actor", methods=["POST"])
def scrape_actor():
    data = request.get_json() or {}
    actor_id = data.get("actor_id")
    run_input = data.get("run_input", {})
    max_items = min(int(data.get("max_items", 10)), 50)
    if not actor_id:
        return jsonify({"error": "actor_id required (e.g. 'aYG0l9s7dbB7j3gbS')"}), 400
    if actor_id not in _ALLOWED_ACTORS:
        return jsonify({"error": "actor_not_allowed", "message": "Only pre-approved Apify actors are permitted.", "allowed": list(_ALLOWED_ACTORS)}), 403
    try:
        results = run_actor_sync(actor_id, run_input, max_items=max_items)
        log_payment("/scrape/actor", 0.10, request.remote_addr)
        return jsonify(agent_response({"actor_id": actor_id, "results": results, "count": len(results)}, "/scrape/actor"))
    except Exception as e:
        return jsonify({"error": "scrape_failed", "message": str(e)}), 502


# ── Marketplace Routes ──────────────────────────────────────────────


@marketplace_bp.route("/marketplace", methods=["GET"])
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


@marketplace_bp.route("/marketplace/list", methods=["POST"])
def marketplace_list():
    """Register your agent's service in the marketplace — requires JWT ownership proof."""
    from agent_identity import verify_jwt
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ey"):
        return jsonify({"error": "unauthorized", "message": "JWT required to list on marketplace. Use /agents/challenge + /agents/verify first."}), 401
    try:
        payload = verify_jwt(auth[7:])
    except Exception:
        return jsonify({"error": "unauthorized", "message": "Invalid or expired JWT."}), 401
    data = request.get_json() or {}
    data["agent_id"] = payload["agent_id"]  # enforce ownership
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


@marketplace_bp.route("/marketplace/listing/<listing_id>", methods=["GET"])
def marketplace_get(listing_id):
    """Get a single marketplace listing."""
    listing = marketplace_get_service(listing_id)
    if not listing:
        return jsonify({"error": "listing not found"}), 404
    return jsonify(listing)


@marketplace_bp.route("/marketplace/delist", methods=["POST"])
def marketplace_delist():
    """Remove your listing from the marketplace."""
    data = request.get_json() or {}
    if not data.get("listing_id") or not data.get("agent_id"):
        return jsonify({"error": "listing_id and agent_id required"}), 400
    removed = marketplace_deregister(data["listing_id"], data["agent_id"])
    return jsonify({"removed": removed})


@marketplace_bp.route("/marketplace/call", methods=["POST"])
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
    # SSRF protection — validate marketplace endpoint
    from security import validate_url, SSRFError
    try:
        validate_url(endpoint, allow_http=False)
    except SSRFError as e:
        return jsonify({"error": f"Blocked endpoint: {e}"}), 403
    try:
        resp = _requests.post(endpoint, json=payload, timeout=60,
                              headers={"User-Agent": "AiPayGen-Marketplace/1.0"})
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
