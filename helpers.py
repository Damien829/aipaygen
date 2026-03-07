"""Shared utilities extracted from app.py — cache, rate limiting, response helpers."""
import json
import os
import time as _time
import functools
from datetime import datetime
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


# ── Per-IP Rate Limiter ──────────────────────────────────────────────────────
_ip_rate: dict = {}
_RATE_LIMIT = 60
_RATE_WINDOW = 60

_identity_rate: dict = {}
_IDENTITY_RATE_LIMIT = 10
_IDENTITY_RATE_WINDOW = 60


def check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    now = _time.time()
    times = [t for t in _ip_rate.get(ip, []) if t > now - _RATE_WINDOW]
    if len(times) >= _RATE_LIMIT:
        _ip_rate[ip] = times
        return False
    times.append(now)
    _ip_rate[ip] = times
    return True


def check_identity_rate_limit(ip: str) -> bool:
    """Stricter rate limit for identity endpoints (10 req/min)."""
    now = _time.time()
    times = [t for t in _identity_rate.get(ip, []) if t > now - _IDENTITY_RATE_WINDOW]
    if len(times) >= _IDENTITY_RATE_LIMIT:
        _identity_rate[ip] = times
        return False
    times.append(now)
    _identity_rate[ip] = times
    return True


# ── Client IP ────────────────────────────────────────────────────────────────

def get_client_ip():
    """Get client IP — trust CF-Connecting-IP (Cloudflare), fall back to REMOTE_ADDR."""
    return request.headers.get("CF-Connecting-IP", request.remote_addr or "unknown").split(",")[0].strip()


# ── Payment Logging ──────────────────────────────────────────────────────────
PAYMENTS_LOG = os.path.join(os.path.dirname(__file__), "payments.jsonl")


def log_payment(endpoint, amount_usd, caller_ip, request_id="", payment_type="x402", tx_hash=""):
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "endpoint": endpoint,
        "amount_usd": amount_usd,
        "ip": caller_ip,
        "request_id": request_id,
        "payment_type": payment_type,
        "tx_hash": tx_hash,
    }
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

def agent_response(data: dict, endpoint: str, network: str = "eip155:8453") -> dict:
    """Wrap result with standard agent-friendly metadata."""
    data["_meta"] = {
        "endpoint": endpoint,
        "model": "claude-haiku-4-5-20251001",
        "network": network,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    return data


def api_error(code: int, error_type: str, message: str, **extra):
    """Standard JSON error response."""
    body = {"error": error_type, "message": message}
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
        if not admin_secret:
            return jsonify({"error": "misconfigured", "message": "ADMIN_SECRET not set"}), 503
        if not token or token != admin_secret:
            return jsonify({"error": "unauthorized", "message": "Admin authentication required"}), 401
        return f(*args, **kwargs)
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

    model_name = model_override or (request.get_json(silent=True) or {}).get("model", "claude-haiku")
    try:
        result = call_model(model_name, messages, system=system, max_tokens=max_tokens)
    except ModelNotFoundError as e:
        return None, str(e)
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
            deduction = deduct_metered(
                api_key, result["input_tokens"], result["output_tokens"],
                cfg["input_cost_per_m"], cfg["output_cost_per_m"],
            )
            if deduction:
                result["metered_cost"] = deduction["cost"]
                result["balance_remaining"] = deduction["balance_remaining"]
                if deduction["balance_remaining"] < 0.10:
                    result["metered_warning"] = f"Low balance: ${deduction['balance_remaining']:.4f} remaining"
    return result, None
