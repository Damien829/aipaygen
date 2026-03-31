"""
SaaS Starter Kit — Auth & Billing Module
Handles API key lifecycle, rate limiting, Stripe checkout, and webhooks.
"""

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from functools import wraps

import stripe
from flask import request, jsonify

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "./data/app.db")

# ── Database Connection ──────────────────────────────────────────────────────


def _conn():
    """Get a SQLite connection with WAL mode and row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.row_factory = sqlite3.Row
    return c


def init_db():
    """Create all tables. Call once at startup."""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                label TEXT DEFAULT '',
                balance_usd REAL DEFAULT 0.0,
                total_spent REAL DEFAULT 0.0,
                call_count INTEGER DEFAULT 0,
                daily_spend_limit REAL DEFAULT 50.0,
                subscription_tier TEXT DEFAULT '',
                subscription_id TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_key ON api_keys(key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_active ON api_keys(is_active)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_spend (
                api_key TEXT NOT NULL,
                date TEXT NOT NULL,
                amount_usd REAL DEFAULT 0.0,
                UNIQUE(api_key, date)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                api_key TEXT,
                stripe_customer_id TEXT,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_email ON users(email)")


# ── API Key Management ───────────────────────────────────────────────────────

# In-memory cache for hot-path key validation
_key_cache: dict = {}
_KEY_CACHE_TTL = 30  # seconds


def generate_key(balance: float = 0.0, label: str = "", source: str = "api") -> dict:
    """Generate a new API key with optional starting balance."""
    key = "apk_" + secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO api_keys (key, label, balance_usd, created_at) VALUES (?, ?, ?, ?)",
            (key, label, balance, now),
        )
    logger.info("Key generated: %s... balance=$%.2f source=%s", key[:12], balance, source)
    return {"key": key, "balance_usd": balance, "label": label, "created_at": now}


def validate_key(key: str) -> dict | None:
    """Fast key validation with caching. Returns key record or None."""
    now = time.time()
    cached = _key_cache.get(key)
    if cached and now - cached[0] < _KEY_CACHE_TTL:
        return cached[1].copy() if cached[1] else None

    with _conn() as c:
        row = c.execute(
            "SELECT key, balance_usd, is_active, daily_spend_limit, subscription_tier "
            "FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
    result = dict(row) if row else None
    _key_cache[key] = (now, result)
    return result.copy() if result else None


def get_key_status(key: str) -> dict | None:
    """Full key details including spend tracking."""
    with _conn() as c:
        row = c.execute(
            "SELECT k.*, d.amount_usd AS daily_spend_today "
            "FROM api_keys k "
            "LEFT JOIN daily_spend d ON d.api_key = k.key AND d.date = date('now') "
            "WHERE k.key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["daily_spend_today"] = result.get("daily_spend_today") or 0.0
    return result


def topup_key(key: str, amount: float) -> dict:
    """Add balance to an existing key."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd + ?, last_used_at = ? "
            "WHERE key = ? AND is_active = 1",
            (amount, now, key),
        )
        row = c.execute("SELECT balance_usd FROM api_keys WHERE key = ?", (key,)).fetchone()
    _key_cache.pop(key, None)
    if not row:
        return {"error": "key_not_found"}
    return {"key": key, "balance_usd": row["balance_usd"], "topped_up": amount}


def deduct(key: str, amount: float, endpoint: str = "") -> bool:
    """Atomically deduct from key balance. Returns False if insufficient funds
    or daily spend limit exceeded."""
    if amount <= 0:
        return True

    # Check daily spend limit
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT balance_usd, daily_spend_limit FROM api_keys "
            "WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
        if not row or row["balance_usd"] < amount:
            conn.execute("ROLLBACK")
            return False

        # Check daily limit
        ds = conn.execute(
            "SELECT amount_usd FROM daily_spend WHERE api_key = ? AND date = ?",
            (key, today),
        ).fetchone()
        spent_today = ds["amount_usd"] if ds else 0.0
        limit = row["daily_spend_limit"] or 50.0
        if spent_today + amount > limit:
            conn.execute("ROLLBACK")
            return False

        # Deduct balance
        conn.execute(
            "UPDATE api_keys SET balance_usd = balance_usd - ?, "
            "total_spent = total_spent + ?, call_count = call_count + 1, "
            "last_used_at = ? WHERE key = ?",
            (amount, amount, datetime.now(timezone.utc).isoformat(), key),
        )
        # Track daily spend
        conn.execute(
            "INSERT INTO daily_spend (api_key, date, amount_usd) VALUES (?, ?, ?) "
            "ON CONFLICT(api_key, date) DO UPDATE SET amount_usd = amount_usd + ?",
            (key, today, amount, amount),
        )
        conn.execute("COMMIT")
        _key_cache.pop(key, None)
        return True
    except Exception:
        conn.execute("ROLLBACK")
        return False
    finally:
        conn.close()


def revoke_key(key: str) -> bool:
    """Deactivate an API key."""
    with _conn() as c:
        cur = c.execute("UPDATE api_keys SET is_active = 0 WHERE key = ?", (key,))
    _key_cache.pop(key, None)
    return cur.rowcount > 0


# ── Rate Limiting ────────────────────────────────────────────────────────────

_rate_buckets: dict = {}  # {key: [timestamp, ...]}
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))


def check_rate_limit(api_key: str) -> bool:
    """Returns True if rate limit is exceeded (caller should return 429)."""
    now = time.time()
    window = 60
    hits = [t for t in _rate_buckets.get(api_key, []) if t > now - window]
    if len(hits) >= RATE_LIMIT_PER_MINUTE:
        return True
    hits.append(now)
    _rate_buckets[api_key] = hits
    return False


# ── Request Authentication Decorator ─────────────────────────────────────────


def require_api_key(cost: float = 0.0):
    """Decorator that validates API key, checks rate limit, and optionally deducts cost.

    Usage:
        @app.route("/api/endpoint")
        @require_api_key(cost=0.01)
        def my_endpoint():
            # request.api_key is available here
            return jsonify({"result": "ok"})
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = request.headers.get("X-API-Key") or request.args.get("api_key", "")
            if not key or not key.startswith("apk_"):
                return jsonify({"error": "Missing or invalid API key"}), 401

            record = validate_key(key)
            if not record:
                return jsonify({"error": "Invalid or deactivated API key"}), 401

            if check_rate_limit(key):
                return jsonify({"error": "Rate limit exceeded", "retry_after": 60}), 429

            if cost > 0 and not deduct(key, cost, endpoint=request.path):
                return jsonify({
                    "error": "Insufficient balance",
                    "balance_usd": record.get("balance_usd", 0),
                    "cost": cost,
                    "topup_url": f"{os.getenv('BASE_URL', '')}/buy-credits",
                }), 402

            request.api_key = key
            request.api_key_record = record
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Stripe Checkout ──────────────────────────────────────────────────────────

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Checkout rate limiting (per IP)
_checkout_rates: dict = {}


def _check_checkout_rate(ip: str) -> bool:
    """Block more than 5 checkout attempts per IP per 10 minutes."""
    now = time.time()
    hits = [t for t in _checkout_rates.get(ip, []) if t > now - 600]
    if len(hits) >= 5:
        return True
    hits.append(now)
    _checkout_rates[ip] = hits
    return False


def create_checkout(amount: float, existing_key: str = "", email: str = "") -> dict:
    """Create a Stripe checkout session for one-time credit purchase.
    Returns {"url": ..., "session_id": ...} or {"error": ...}."""
    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe not configured"}

    allowed_amounts = (1, 5, 10, 20, 50, 100)
    if amount not in allowed_amounts:
        return {"error": f"Amount must be one of: {', '.join(f'${a}' for a in allowed_amounts)}"}

    action = "topup" if existing_key else "new"
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{os.getenv('APP_NAME', 'API')} Credits — ${amount:.0f}",
                        "description": f"Prepaid API credits worth ${amount:.0f}.",
                    },
                    "unit_amount": int(amount * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            client_reference_id=existing_key or "new",
            metadata={
                "amount": str(amount),
                "action": action,
                **({"api_key": existing_key} if existing_key else {}),
            },
            success_url=f"{BASE_URL}/buy-credits/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/buy-credits?canceled=1",
            billing_address_collection="required",
            **({"customer_email": email} if email else {}),
        )
        return {"url": session.url, "session_id": session.id}
    except Exception as e:
        logger.error("Stripe checkout failed: %s", e)
        return {"error": "Payment processing failed"}


def create_subscription_checkout(price_id: str, email: str = "",
                                  existing_key: str = "") -> dict:
    """Create a Stripe subscription checkout session.
    price_id should be a Stripe Price ID (price_xxx) created in your dashboard."""
    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe not configured"}

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            metadata={
                "action": "subscription",
                **({"api_key": existing_key} if existing_key else {}),
            },
            success_url=f"{BASE_URL}/subscribe/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/subscribe?canceled=1",
            billing_address_collection="required",
            **({"customer_email": email} if email else {}),
        )
        return {"url": session.url, "session_id": session.id}
    except Exception as e:
        logger.error("Stripe subscription checkout failed: %s", e)
        return {"error": "Subscription creation failed"}


# ── Stripe Webhook Handler ───────────────────────────────────────────────────


def _is_event_processed(event_id: str) -> bool:
    """Idempotency check — prevent processing duplicate Stripe events."""
    with _conn() as c:
        row = c.execute("SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,)).fetchone()
    return row is not None


def _mark_event_processed(event_id: str):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO processed_events (event_id, processed_at) VALUES (?, ?)",
            (event_id, datetime.now(timezone.utc).isoformat()),
        )


def handle_webhook(payload: bytes, signature: str) -> tuple[dict, int]:
    """Process a Stripe webhook event. Returns (response_dict, status_code).
    Wire this to your POST /stripe/webhook route."""
    if not STRIPE_WEBHOOK_SECRET:
        return {"error": "Webhook secret not configured"}, 503

    try:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        return {"error": "Invalid signature"}, 400

    event_id = event.get("id", "")
    if event_id and _is_event_processed(event_id):
        return {"received": True, "duplicate": True}, 200

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {})
        amount = float(meta.get("amount", 0))

        # Validate metadata amount against actual Stripe charge
        stripe_amount = session.get("amount_total", 0) / 100
        if amount != stripe_amount:
            logger.warning("Amount mismatch: meta=%.2f actual=%.2f", amount, stripe_amount)
            amount = stripe_amount

        action = meta.get("action", "new")
        api_key = meta.get("api_key", "")

        if amount > 0:
            if action == "topup" and api_key:
                topup_key(api_key, amount)
                logger.info("Top-up $%.2f for key %s...", amount, api_key[:12])
            else:
                new = generate_key(balance=amount, label="credit-pack", source="stripe")
                api_key = new["key"]
                logger.info("New key created: %s... balance=$%.2f", api_key[:12], amount)

    elif event["type"] == "customer.subscription.deleted":
        sub_id = event["data"]["object"].get("id", "")
        if sub_id:
            with _conn() as c:
                row = c.execute(
                    "SELECT key FROM api_keys WHERE subscription_id = ? AND is_active = 1",
                    (sub_id,),
                ).fetchone()
                if row:
                    c.execute(
                        "UPDATE api_keys SET subscription_tier = '', subscription_id = '' "
                        "WHERE key = ?",
                        (row["key"],),
                    )
            logger.info("Subscription %s canceled", sub_id)

    if event_id:
        _mark_event_processed(event_id)

    return {"received": True}, 200


# ── Admin Auth ───────────────────────────────────────────────────────────────

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


def require_admin(f):
    """Decorator for admin-only routes. Checks X-Admin-Key header."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not ADMIN_SECRET:
            return jsonify({"error": "Admin not configured"}), 503
        key = request.headers.get("X-Admin-Key", "")
        if not secrets.compare_digest(key, ADMIN_SECRET):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper
