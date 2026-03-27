"""Prepaid API key management. Keys funded upfront, deducted per call."""
import hashlib
import json
import sqlite3
import os
import secrets
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "api_keys.db")

_key_cache = {}
_KEY_CACHE_TTL = 30


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.row_factory = sqlite3.Row
    return c


def init_keys_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                label TEXT DEFAULT '',
                balance_usd REAL DEFAULT 0.0,
                total_spent REAL DEFAULT 0.0,
                call_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_key ON api_keys(key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_balance ON api_keys(balance_usd)")
        # Migrations
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN source TEXT DEFAULT 'unknown'")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN first_used_at TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN referral_code TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # New columns for spending limits and key scoping
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN daily_spend_limit REAL DEFAULT 10.0")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN allowed_tools TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # Subscription columns
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN subscription_tier TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN subscription_id TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN monthly_calls_remaining INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN subscription_reset_date TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_referral ON api_keys(referral_code)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_tier ON api_keys(subscription_tier)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_active ON api_keys(is_active)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_source ON api_keys(source)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_created ON api_keys(created_at)")

        # Daily spend tracking table
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_spend (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT NOT NULL,
                date TEXT NOT NULL,
                amount_usd REAL DEFAULT 0.0,
                UNIQUE(api_key, date)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_daily_spend_key ON daily_spend(api_key, date)")

        # Stripe event idempotency table
        c.execute("""
            CREATE TABLE IF NOT EXISTS processed_stripe_events (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL
            )
        """)

        # Trial credits tracking (one per IP)
        c.execute("""
            CREATE TABLE IF NOT EXISTS trial_credits_used (
                ip_hash TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
        """)

        # Key generation rate limiting per IP
        c.execute("""
            CREATE TABLE IF NOT EXISTS key_gen_rate (
                ip_hash TEXT NOT NULL,
                date TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                UNIQUE(ip_hash, date)
            )
        """)


def generate_key(initial_balance: float = 0.0, label: str = "", source: str = "unknown") -> dict:
    key = "apk_" + secrets.token_urlsafe(32)
    referral_code = hashlib.sha256(key.encode()).hexdigest()[:8]
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO api_keys (key, label, balance_usd, created_at, source, referral_code) VALUES (?, ?, ?, ?, ?, ?)",
            (key, label, initial_balance, now, source, referral_code),
        )
    # Audit log
    try:
        from billing_audit import log_audit
        log_audit("key_generated", api_key=key, amount_usd=initial_balance,
                  balance_after=initial_balance, metadata=json.dumps({"source": source, "label": label}))
    except Exception:
        pass
    return {"key": key, "balance_usd": initial_balance, "label": label, "created_at": now, "source": source,
            "referral_code": referral_code}


def get_key_by_referral_code(code: str) -> dict | None:
    """Look up an API key by its referral code."""
    if not code:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT key, label, balance_usd, referral_code FROM api_keys WHERE referral_code = ? AND is_active = 1",
            (code,),
        ).fetchone()
    return dict(row) if row else None


def topup_key(key: str, amount: float) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd + ?, last_used_at = ? WHERE key = ? AND is_active = 1",
            (amount, now, key),
        )
        row = c.execute("SELECT balance_usd FROM api_keys WHERE key = ?", (key,)).fetchone()
    if not row:
        return {"error": "key_not_found"}
    _key_cache.pop(key, None)
    # Audit log
    try:
        from billing_audit import log_audit
        log_audit("topup", api_key=key, amount_usd=amount, balance_after=row["balance_usd"])
    except Exception:
        pass
    return {"key": key, "balance_usd": row["balance_usd"], "topped_up": amount}


def get_key_status(key: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT k.key, k.label, k.balance_usd, k.total_spent, k.call_count, k.is_active, "
            "k.created_at, k.last_used_at, k.source, k.first_used_at, k.referral_code, "
            "k.daily_spend_limit, k.allowed_tools, k.subscription_tier, k.subscription_id, "
            "k.monthly_calls_remaining, k.subscription_reset_date, "
            "d.amount_usd as daily_spend_today "
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


def validate_key(key: str) -> dict | None:
    """Lightweight check — returns key record if active, None otherwise."""
    import time
    now = time.time()
    cached = _key_cache.get(key)
    if cached and now - cached[0] < _KEY_CACHE_TTL:
        return cached[1].copy() if cached[1] else None

    with _conn() as c:
        row = c.execute(
            "SELECT key, balance_usd, is_active, daily_spend_limit, allowed_tools, subscription_tier, monthly_calls_remaining FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
    result = dict(row) if row else None
    _key_cache[key] = (now, result)
    return result.copy() if result else None


def get_allowed_tools(key: str) -> list[str] | None:
    """Return list of allowed tools for this key, or None if unrestricted."""
    with _conn() as c:
        row = c.execute(
            "SELECT allowed_tools FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
    if not row or not row["allowed_tools"]:
        return None
    return [t.strip() for t in row["allowed_tools"].split(",") if t.strip()]


def set_allowed_tools(key: str, tools: list[str]) -> bool:
    """Set allowed tools for a key. Pass empty list to remove restrictions."""
    tools_str = ",".join(tools) if tools else ""
    with _conn() as c:
        cur = c.execute(
            "UPDATE api_keys SET allowed_tools = ? WHERE key = ? AND is_active = 1",
            (tools_str, key),
        )
    return cur.rowcount > 0


def set_daily_spend_limit(key: str, limit: float) -> bool:
    """Set daily spend limit for a key. Default is $10/day, max $50/day."""
    limit = max(0.01, min(limit, 50.0))
    with _conn() as c:
        cur = c.execute(
            "UPDATE api_keys SET daily_spend_limit = ? WHERE key = ? AND is_active = 1",
            (limit, key),
        )
    return cur.rowcount > 0


def check_daily_spend(key: str, amount: float) -> tuple[bool, float]:
    """Check if adding `amount` would exceed daily spend limit.
    Returns (allowed, remaining_today)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _conn() as c:
        row = c.execute(
            "SELECT daily_spend_limit FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
        if not row:
            return False, 0.0
        limit = row["daily_spend_limit"] or 10.0

        ds = c.execute(
            "SELECT amount_usd FROM daily_spend WHERE api_key = ? AND date = ?",
            (key, today),
        ).fetchone()
        spent = ds["amount_usd"] if ds else 0.0

    remaining = limit - spent
    return (spent + amount) <= limit, remaining


def _record_daily_spend(key: str, amount: float):
    """Record spending for daily limit tracking."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    c = sqlite3.connect(DB_PATH, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            """INSERT INTO daily_spend (api_key, date, amount_usd)
               VALUES (?, ?, ?)
               ON CONFLICT(api_key, date)
               DO UPDATE SET amount_usd = amount_usd + ?""",
            (key, today, amount, amount),
        )
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
    finally:
        c.close()


def deduct(key: str, amount: float, endpoint: str = "", ip: str = "") -> bool:
    """Atomically deduct amount from key balance. Returns False if insufficient funds,
    invalid amount, or daily spend limit exceeded."""
    if amount < 0:
        return False
    # Check daily spend limit
    allowed, _remaining = check_daily_spend(key, amount)
    if not allowed:
        return False
    now = datetime.now(timezone.utc).isoformat()
    c = sqlite3.connect(DB_PATH, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    try:
        c.execute("BEGIN IMMEDIATE")
        cur = c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd - ?, total_spent = total_spent + ?, "
            "call_count = call_count + 1, last_used_at = ?, "
            "first_used_at = CASE WHEN first_used_at IS NULL THEN ? ELSE first_used_at END "
            "WHERE key = ? AND is_active = 1 AND balance_usd >= ?",
            (amount, amount, now, now, key, amount),
        )
        if cur.rowcount > 0:
            # Get new balance for audit
            new_bal = c.execute("SELECT balance_usd FROM api_keys WHERE key = ?", (key,)).fetchone()
            c.execute("COMMIT")
            _key_cache.pop(key, None)
            # Record daily spend
            _record_daily_spend(key, amount)
            # Audit log
            try:
                from billing_audit import log_audit
                log_audit("deduction", api_key=key, amount_usd=amount,
                          balance_after=new_bal[0] if new_bal else 0,
                          endpoint=endpoint, ip=ip)
            except Exception:
                pass
            # Trigger low-balance email when credits nearly exhausted
            if new_bal and new_bal[0] < 0.02:
                try:
                    from accounts import get_account_by_key
                    acct = get_account_by_key(key)
                    if acct and acct.get("email"):
                        from routes.auth import _schedule_email
                        _schedule_email(acct["email"], key, "low_balance", delay_seconds=60)
                except Exception:
                    pass
            return True
        else:
            c.execute("COMMIT")
            return False
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def deduct_metered(key: str, input_tokens: int, output_tokens: int,
                   input_rate: float, output_rate: float,
                   endpoint: str = "", ip: str = "") -> dict | None:
    """Deduct actual token cost from key balance. Returns cost info or None if insufficient.

    Rates are USD per million tokens.
    Uses BEGIN IMMEDIATE to prevent race conditions (same pattern as deduct()).
    """
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    if cost < 0:
        return None
    # Check daily spend limit
    allowed, _remaining = check_daily_spend(key, cost)
    if not allowed:
        return None
    now = datetime.now(timezone.utc).isoformat()
    c = sqlite3.connect(DB_PATH, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    try:
        c.execute("BEGIN IMMEDIATE")
        cur = c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd - ?, total_spent = total_spent + ?, "
            "call_count = call_count + 1, last_used_at = ?, "
            "first_used_at = CASE WHEN first_used_at IS NULL THEN ? ELSE first_used_at END "
            "WHERE key = ? AND is_active = 1 AND balance_usd >= ?",
            (cost, cost, now, now, key, cost),
        )
        if cur.rowcount == 0:
            c.execute("ROLLBACK")
            return None
        new_balance = c.execute(
            "SELECT balance_usd FROM api_keys WHERE key = ?", (key,),
        ).fetchone()["balance_usd"]
        c.execute("COMMIT")
        _key_cache.pop(key, None)
        # Record daily spend
        _record_daily_spend(key, cost)
        # Audit log
        try:
            from billing_audit import log_audit
            log_audit("deduction", api_key=key, amount_usd=cost,
                      balance_after=new_balance, endpoint=endpoint, ip=ip,
                      metadata=json.dumps({"input_tokens": input_tokens, "output_tokens": output_tokens}))
        except Exception:
            pass
        return {"cost": round(cost, 8), "balance_remaining": round(new_balance, 8)}
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def rotate_key(old_key: str) -> dict | None:
    """Generate a new key and transfer balance from old key. Old key is deactivated."""
    c = sqlite3.connect(DB_PATH, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT * FROM api_keys WHERE key = ? AND is_active = 1",
            (old_key,),
        ).fetchone()
        if not row:
            c.execute("ROLLBACK")
            return None

        new_key = "apk_" + secrets.token_urlsafe(32)
        new_referral = hashlib.sha256(new_key.encode()).hexdigest()[:8]
        now = datetime.now(timezone.utc).isoformat()
        balance = row["balance_usd"]

        # Deactivate old key
        c.execute("UPDATE api_keys SET is_active = 0, last_used_at = ? WHERE key = ?",
                  (now, old_key))

        # Create new key with transferred balance
        c.execute(
            "INSERT INTO api_keys (key, label, balance_usd, total_spent, call_count, "
            "is_active, created_at, last_used_at, source, referral_code, "
            "daily_spend_limit, allowed_tools) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
            (new_key, row["label"], balance, row["total_spent"], row["call_count"],
             now, now, row["source"], new_referral,
             row["daily_spend_limit"], row["allowed_tools"]),
        )
        c.execute("COMMIT")

        # Audit log
        try:
            from billing_audit import log_audit
            log_audit("key_rotated", api_key=old_key, amount_usd=balance,
                      balance_after=balance,
                      metadata=json.dumps({"new_key_prefix": new_key[:12]}))
        except Exception:
            pass

        return {
            "new_key": new_key,
            "old_key_deactivated": old_key[:12] + "...",
            "balance_usd": balance,
            "referral_code": new_referral,
        }
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def deactivate_key(key: str) -> bool:
    """Deactivate an API key."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute(
            "UPDATE api_keys SET is_active = 0, last_used_at = ? WHERE key = ? AND is_active = 1",
            (now, key),
        )
    if cur.rowcount > 0:
        try:
            from billing_audit import log_audit
            log_audit("key_deactivated", api_key=key)
        except Exception:
            pass
        return True
    return False


# ── Stripe Idempotency ─────────────────────────────────────────────────────

def is_stripe_event_processed(event_id: str) -> bool:
    """Check if a Stripe event has already been processed."""
    with _conn() as c:
        row = c.execute(
            "SELECT event_id FROM processed_stripe_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return row is not None


def mark_stripe_event_processed(event_id: str):
    """Mark a Stripe event as processed."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO processed_stripe_events (event_id, processed_at) VALUES (?, ?)",
            (event_id, now),
        )


# ── Trial Credits IP Tracking ──────────────────────────────────────────────

def has_received_trial_credits(ip: str) -> bool:
    """Check if an IP has already received trial credits."""
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
    with _conn() as c:
        row = c.execute(
            "SELECT ip_hash FROM trial_credits_used WHERE ip_hash = ?",
            (ip_hash,),
        ).fetchone()
    return row is not None


def mark_trial_credits_used(ip: str):
    """Mark that an IP has received trial credits."""
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO trial_credits_used (ip_hash, created_at) VALUES (?, ?)",
            (ip_hash, now),
        )


# ── Key Generation Rate Limiting ───────────────────────────────────────────

def check_key_gen_rate(ip: str, max_per_day: int = 5) -> bool:
    """Check if IP can generate another key today. Returns True if allowed."""
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _conn() as c:
        row = c.execute(
            "SELECT count FROM key_gen_rate WHERE ip_hash = ? AND date = ?",
            (ip_hash, today),
        ).fetchone()
    if row and row["count"] >= max_per_day:
        return False
    return True


def record_key_gen(ip: str):
    """Record a key generation for rate limiting."""
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _conn() as c:
        c.execute(
            """INSERT INTO key_gen_rate (ip_hash, date, count)
               VALUES (?, ?, 1)
               ON CONFLICT(ip_hash, date)
               DO UPDATE SET count = count + 1""",
            (ip_hash, today),
        )


# ── Tier Detection ─────────────────────────────────────────────────────────

def get_key_tier(key: str) -> str:
    """Determine rate limit tier based on balance or subscription tier.
    Free (no key): 20 req/min
    Starter ($0-$2): 60 req/min
    Pro ($2-$10): 120 req/min
    Enterprise ($10+): 300 req/min
    Subscription hobby: 60 req/min
    Subscription pro: 120 req/min
    Subscription business: 300 req/min
    """
    with _conn() as c:
        row = c.execute(
            "SELECT balance_usd, subscription_tier FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
    if not row:
        return "free"
    sub_tier = row["subscription_tier"] if row["subscription_tier"] else None
    if sub_tier:
        return {"hobby": "starter", "starter": "starter", "pro": "pro", "business": "enterprise", "enterprise": "enterprise"}.get(sub_tier, "starter")
    bal = row["balance_usd"]
    if bal >= 10.0:
        return "enterprise"
    if bal >= 2.0:
        return "pro"
    return "starter"


def get_tier_rate_limit(tier: str) -> int:
    """Return requests per minute for a tier."""
    return {
        "free": 20,
        "starter": 60,
        "pro": 120,
        "enterprise": 300,
    }.get(tier, 20)


# ── Subscription Management ──────────────────────────────────────────────

SUBSCRIPTION_TIERS = {
    "starter": {"price_usd": 4.99, "monthly_calls": 500, "model_tier": "standard"},
    "pro": {"price_usd": 19.99, "monthly_calls": 2000, "model_tier": "priority"},
    "enterprise": {"price_usd": 49.99, "monthly_calls": 10000, "model_tier": "premium"},
}


def set_subscription(key: str, tier: str, subscription_id: str, reset_date: str) -> bool:
    """Activate or update a subscription for an API key."""
    if tier not in SUBSCRIPTION_TIERS:
        return False
    monthly_calls = SUBSCRIPTION_TIERS[tier]["monthly_calls"]
    with _conn() as c:
        cur = c.execute(
            "UPDATE api_keys SET subscription_tier = ?, subscription_id = ?, "
            "monthly_calls_remaining = ?, subscription_reset_date = ? "
            "WHERE key = ? AND is_active = 1",
            (tier, subscription_id, monthly_calls, reset_date, key),
        )
    return cur.rowcount > 0


def cancel_subscription(key: str) -> bool:
    """Cancel subscription for an API key. Keep remaining calls until reset date."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE api_keys SET subscription_tier = '', subscription_id = '' "
            "WHERE key = ? AND is_active = 1",
            (key,),
        )
    return cur.rowcount > 0


def decrement_subscription_call(key: str) -> bool:
    """Decrement monthly_calls_remaining by 1. Returns False if no calls left."""
    c = sqlite3.connect(DB_PATH, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    try:
        c.execute("BEGIN IMMEDIATE")
        cur = c.execute(
            "UPDATE api_keys SET monthly_calls_remaining = monthly_calls_remaining - 1 "
            "WHERE key = ? AND is_active = 1 AND monthly_calls_remaining > 0 "
            "AND subscription_tier != ''",
            (key,),
        )
        if cur.rowcount > 0:
            c.execute("COMMIT")
            return True
        c.execute("COMMIT")
        return False
    except Exception:
        c.execute("ROLLBACK")
        return False
    finally:
        c.close()


def reset_subscription_calls(key: str) -> bool:
    """Reset monthly calls to tier allowance. Called on billing date."""
    with _conn() as c:
        row = c.execute(
            "SELECT subscription_tier FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
    if not row or not row["subscription_tier"]:
        return False
    tier = row["subscription_tier"]
    monthly_calls = SUBSCRIPTION_TIERS.get(tier, {}).get("monthly_calls", 0)
    next_reset = (datetime.now(timezone.utc).replace(day=1) + __import__("datetime").timedelta(days=32)).replace(day=1).isoformat()[:10]
    with _conn() as c:
        c.execute(
            "UPDATE api_keys SET monthly_calls_remaining = ?, subscription_reset_date = ? WHERE key = ?",
            (monthly_calls, next_reset, key),
        )
    return True


def get_subscription_status(key: str) -> dict | None:
    """Get subscription details for an API key."""
    with _conn() as c:
        row = c.execute(
            "SELECT subscription_tier, subscription_id, monthly_calls_remaining, subscription_reset_date "
            "FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
    if not row or not row["subscription_tier"]:
        return None
    tier = row["subscription_tier"]
    tier_info = SUBSCRIPTION_TIERS.get(tier, {})
    return {
        "tier": tier,
        "price_usd": tier_info.get("price_usd", 0),
        "monthly_calls_total": tier_info.get("monthly_calls", 0),
        "monthly_calls_remaining": row["monthly_calls_remaining"],
        "monthly_calls_used": tier_info.get("monthly_calls", 0) - row["monthly_calls_remaining"],
        "model_tier": tier_info.get("model_tier", "standard"),
        "subscription_id": row["subscription_id"],
        "reset_date": row["subscription_reset_date"],
    }
