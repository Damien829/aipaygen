"""Shared utilities extracted from app.py — cache, rate limiting, response helpers."""
import hmac
import json
import os

APP_VERSION = "1.9.5"
import time as _time
import hashlib as _hashlib
import threading
_cache_lock = threading.Lock()
import functools
from datetime import datetime, timezone
from flask import request, jsonify


# ── TTL Response Cache ───────────────────────────────────────────────────────
_ttl_cache: dict = {}


def cache_get(key: str):
    entry = _ttl_cache.get(key)
    if entry and _time.time() < entry[1]:
        return entry[0]
    return None


def cache_set(key: str, data, ttl: int):
    _ttl_cache[key] = (data, _time.time() + ttl)


def _cache_cleanup():
    """Remove expired entries from cache and rate limit dicts."""
    with _cache_lock:
        now = _time.time()
        expired = [k for k, v in _ttl_cache.items() if now >= v[1]]
        for k in expired:
            del _ttl_cache[k]
        for d in (_ip_rate, _identity_rate, _endpoint_rate):
            stale = [k for k, v in d.items() if not v or max(v) < now - 120]
            for k in stale:
                del d[k]


# ── Per-IP Rate Limiter ──────────────────────────────────────────────────────
_ip_rate: dict = {}
_endpoint_rate: dict = {}
_RATE_LIMIT = 60
_RATE_WINDOW = 60

_identity_rate: dict = {}
_IDENTITY_RATE_LIMIT = 10
_IDENTITY_RATE_WINDOW = 60


def check_rate_limit(ip: str, limit_override: int = None) -> bool:
    """Returns True if request is allowed, False if rate limited.

    Args:
        limit_override: Override the default rate limit (e.g. 20 for unauth, 120 for auth).
    """
    limit = limit_override or _RATE_LIMIT
    now = _time.time()
    times = [t for t in _ip_rate.get(ip, []) if t > now - _RATE_WINDOW][-limit:]
    if len(times) >= limit:
        _ip_rate[ip] = times
        return False
    times.append(now)
    _ip_rate[ip] = times
    return True


def get_rate_limit_info(ip: str, limit_override: int = None) -> dict:
    """Return current rate limit state for the given IP.

    Args:
        limit_override: Override the default rate limit (e.g. tier-specific limit).

    Returns dict with limit, remaining, and reset (unix timestamp).
    """
    limit = limit_override or _RATE_LIMIT
    now = _time.time()
    times = [t for t in _ip_rate.get(ip, []) if t > now - _RATE_WINDOW]
    remaining = max(0, limit - len(times))
    # Reset = when the oldest request in the window expires
    reset_ts = int(times[0] + _RATE_WINDOW) if times else int(now + _RATE_WINDOW)
    return {
        "limit": limit,
        "remaining": remaining,
        "reset": reset_ts,
        "window": _RATE_WINDOW,
    }


def check_identity_rate_limit(ip: str) -> bool:
    """Stricter rate limit for identity endpoints (10 req/min)."""
    now = _time.time()
    times = [t for t in _identity_rate.get(ip, []) if t > now - _IDENTITY_RATE_WINDOW][-_IDENTITY_RATE_LIMIT:]
    if len(times) >= _IDENTITY_RATE_LIMIT:
        _identity_rate[ip] = times
        return False
    times.append(now)
    _identity_rate[ip] = times
    return True


# ── Per-Endpoint Rate Limiter ────────────────────────────────────────────────


def _check_endpoint_rate(ip: str, bucket: str, limit: int, window: int = 60) -> bool:
    """Generic per-endpoint rate limiter. Returns True if allowed."""
    now = _time.time()
    key = f"{bucket}:{ip}"
    times = [t for t in _endpoint_rate.get(key, []) if t > now - window][-limit:]
    if len(times) >= limit:
        _endpoint_rate[key] = times
        return False
    times.append(now)
    _endpoint_rate[key] = times
    return True


def rate_limit(limit: int, window: int = 60, bucket: str = None):
    """Decorator: per-endpoint rate limit. Usage: @rate_limit(5) on a route."""
    def decorator(f):
        _bucket = bucket or f.__name__
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            ip = get_client_ip()
            if not _check_endpoint_rate(ip, _bucket, limit, window):
                return jsonify({"error": "rate_limited", "message": f"Limit: {limit} req/{window}s"}), 429
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Client IP ────────────────────────────────────────────────────────────────

def get_client_ip():
    """Get client IP — trust CF-Connecting-IP (Cloudflare), fall back to REMOTE_ADDR."""
    return request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown").split(",")[0].strip()


# ── Payment Logging ──────────────────────────────────────────────────────────
PAYMENTS_LOG = os.path.join(os.path.dirname(__file__), "payments.jsonl")
_payment_log_lock = threading.Lock()


def log_payment(endpoint, amount_usd, caller_ip, request_id="", payment_type="x402", tx_hash=""):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "amount_usd": amount_usd,
        "ip": _hashlib.sha256(caller_ip.encode()).hexdigest()[:16],
        "request_id": request_id,
        "payment_type": payment_type,
        "tx_hash": tx_hash,
    }
    with _payment_log_lock:
        with open(PAYMENTS_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")


# ── JSON Parsing ─────────────────────────────────────────────────────────────
import re as _re


def parse_json_from_claude(text):
    """Extract a JSON object from Claude's response even if wrapped in markdown."""
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
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


# ── Response Helpers ─────────────────────────────────────────────────────────

def agent_response(data: dict, endpoint: str, network: str = "eip155:8453", model: str = "claude-haiku-4-5-20251001") -> dict:
    """Wrap result with standard agent-friendly metadata."""
    data["_meta"] = {
        "endpoint": endpoint,
        "model": model,
        "network": network,
        "ts": datetime.now(timezone.utc).isoformat() + "Z",
    }
    return data


def api_error(code: int, error_type: str, message: str, **extra):
    """Standard JSON error response with request ID for support reference."""
    body = {"error": error_type, "message": message}
    # Include request_id if available (set by before_request hook in app.py)
    try:
        req_id = getattr(request, '_request_id', None)
        if req_id:
            body["request_id"] = req_id
    except RuntimeError:
        pass  # Outside request context
    body.update(extra)
    return jsonify(body), code


# ── Auth Decorators ──────────────────────────────────────────────────────────


def require_admin(f):
    """Decorator to require admin auth via Bearer token or X-Admin-Key header."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        admin_secret = os.getenv("ADMIN_SECRET", "")
        token = ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        if not token:
            token = request.headers.get("X-Admin-Key", "")
        if not token:
            token = request.form.get("key", "")
        if not admin_secret:
            return jsonify({"error": "misconfigured", "message": "ADMIN_SECRET not set"}), 503
        if not token or not hmac.compare_digest(token, admin_secret):
            return jsonify({"error": "unauthorized", "message": "Admin authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


def require_api_key(f):
    """Decorator to require a valid API key via Bearer token."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        from api_keys import validate_key
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer apk_"):
            key_data = validate_key(auth[7:])
            if key_data:
                request.api_key = auth[7:]
                request.key_data = key_data
                return f(*args, **kwargs)
        # Also allow admin key
        admin_secret = os.getenv("ADMIN_SECRET", "")
        if admin_secret and auth == f"Bearer {admin_secret}":
            request.api_key = None
            request.key_data = {"admin": True}
            return f(*args, **kwargs)
        return jsonify({"error": "API key required", "hint": "Pass Authorization: Bearer apk_..."}), 401
    return wrapper


def require_verified_agent(f):
    """Decorator: require JWT from a verified agent wallet."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        from agent_identity import verify_jwt
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


def call_llm(messages, system="", max_tokens=1024, endpoint="unknown", model_override=None):
    """Route LLM call through model_router. Reads 'model' from request JSON if not overridden."""
    from model_router import call_model, get_model_config, ModelNotFoundError
    from api_keys import deduct_metered
    from discovery_engine import track_cost
    import hashlib

    _llm_start = _time.time()
    model_name = model_override or (request.get_json(silent=True) or {}).get("model", "claude-haiku")

    # ── Response cache: same prompt → same result within 60s ──────────────
    cache_input = f"{model_name}:{system}:{str(messages)}"
    cache_key = f"llm:{hashlib.md5(cache_input.encode()).hexdigest()}"
    cached = cache_get(cache_key)
    if cached is not None:
        cached["_cached"] = True
        return cached, None
    # Force free local model for free tier calls — zero provider cost
    is_free = request.environ.get("X_FREE_TIER") == "1"
    if is_free:
        model_name = "claude-haiku"  # Free tier uses cheap Haiku (~$0.001/call)
        max_tokens = min(max_tokens, 512)
    # Flat pricing: force haiku — user pays fixed price, can't request expensive models
    pricing_mode = request.environ.get("X_PRICING_MODE", "")
    if pricing_mode == "flat":
        model_name = "claude-haiku"
        max_tokens = min(max_tokens, 2048)
    try:
        result = call_model(model_name, messages, system=system, max_tokens=max_tokens)
    except ModelNotFoundError:
        return None, "Model not found"
    try:
        track_cost(endpoint, result["model_id"], result["input_tokens"], result["output_tokens"])
    except Exception:
        pass
    # Metered deduction if applicable
    api_key = request.environ.get("X_APIKEY_BYPASS", "")
    pricing_mode = request.environ.get("X_PRICING_MODE", "flat")
    if api_key and pricing_mode == "metered":
        cfg = get_model_config(model_name)
        estimated_cost = (result["input_tokens"] * cfg["input_cost_per_m"] + result["output_tokens"] * cfg["output_cost_per_m"]) / 1_000_000
        if estimated_cost > 1.00:
            result["metered_warning"] = f"Request cost ${estimated_cost:.4f} exceeds $1.00 cap — deduction skipped"
        else:
            _ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
            deduction = deduct_metered(
                api_key, result["input_tokens"], result["output_tokens"],
                cfg["input_cost_per_m"], cfg["output_cost_per_m"],
                endpoint=endpoint, ip=_ip,
            )
            if deduction:
                result["metered_cost"] = deduction["cost"]
                result["balance_remaining"] = deduction["balance_remaining"]
                if deduction["balance_remaining"] < 0.10:
                    result["metered_warning"] = f"Low balance: ${deduction['balance_remaining']:.4f} remaining"
                # Fire low_balance webhooks if configured
                try:
                    from webhook_dispatch import check_low_balance_webhooks
                    check_low_balance_webhooks(api_key, deduction["balance_remaining"])
                except Exception:
                    pass
    # Cost transparency: add _billing to every paid response
    if api_key:
        flat_cost = request.environ.get("X_FLAT_COST", "")
        if pricing_mode == "flat" and flat_cost:
            result["_billing"] = {
                "cost_usd": float(flat_cost),
                "pricing": "flat",
                "payment": "api_key",
            }
        elif pricing_mode == "metered" and "metered_cost" in result:
            result["_billing"] = {
                "cost_usd": result["metered_cost"],
                "balance_remaining": result.get("balance_remaining", 0),
                "pricing": "metered",
                "payment": "api_key",
            }
    # Auto-capture interesting paid calls for showcase
    api_key = request.environ.get("X_APIKEY_BYPASS", "")
    if api_key and not is_free:
        try:
            from showcase import log_showcase, is_interesting
            elapsed_ms = int((_time.time() - _llm_start) * 1000)
            tool = endpoint.strip("/").split("/")[-1] if "/" in endpoint else endpoint
            if is_interesting(tool, elapsed_ms):
                inp = ""
                if messages:
                    last = messages[-1].get("content", "") if isinstance(messages[-1], dict) else str(messages[-1])
                    inp = str(last)[:100]
                out = str(result.get("text", result.get("content", "")))[:200] if isinstance(result, dict) else ""
                log_showcase(tool, inp, out, elapsed_ms, model_name)
        except Exception:
            pass
    # Cache successful result for 60s
    cache_set(cache_key, result, ttl=60)
    return result, None


# Periodic cache cleanup
import threading as _threading


def _start_cache_cleanup():
    def _loop():
        while True:
            _time.sleep(300)
            try:
                _cache_cleanup()
            except Exception:
                pass
    t = _threading.Thread(target=_loop, daemon=True)
    t.start()


_start_cache_cleanup()
