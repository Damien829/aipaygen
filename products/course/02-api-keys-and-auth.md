# Lesson 02: API Keys and Authentication

## What You Will Build

A prepaid API key system: generation with the `apk_` prefix, validation with caching, balance tracking, atomic deductions, rate limiting by tier, daily spend limits, and key rotation. This is how you turn a free API into a business.

## Key Generation

The `apk_` prefix is a deliberate design choice. It makes API keys instantly recognizable in logs, environment variables, and support tickets. GitHub's secret scanning knows to flag keys with known prefixes — you want yours to be identifiable too.

```python
import secrets
import hashlib
from datetime import datetime, timezone

def generate_key(initial_balance: float = 0.0, label: str = "",
                 source: str = "unknown") -> dict:
    key = "apk_" + secrets.token_urlsafe(32)
    referral_code = hashlib.sha256(key.encode()).hexdigest()[:8]
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO api_keys (key, label, balance_usd, created_at, source, referral_code) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key, label, initial_balance, now, source, referral_code),
        )
    return {"key": key, "balance_usd": initial_balance, "referral_code": referral_code}
```

`secrets.token_urlsafe(32)` generates a cryptographically secure random string. Never use `uuid4()` or `random` for API keys — those are not designed for security.

The `source` field tracks where the key came from (quick-key page, Stripe checkout, registration form). This data is gold for understanding your conversion funnel.

## Key Validation with Caching

Every API request needs to validate the key. Hitting SQLite on every single request is wasteful — the key data rarely changes between calls. A 30-second TTL cache keeps things fast:

```python
_key_cache = {}
_KEY_CACHE_TTL = 30

def validate_key(key: str) -> dict | None:
    """Lightweight check — returns key record if active, None otherwise."""
    import time
    now = time.time()
    cached = _key_cache.get(key)
    if cached and now - cached[0] < _KEY_CACHE_TTL:
        return cached[1].copy() if cached[1] else None

    with _conn() as c:
        row = c.execute(
            "SELECT key, balance_usd, is_active, daily_spend_limit, "
            "allowed_tools, subscription_tier, monthly_calls_remaining "
            "FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
    result = dict(row) if row else None
    _key_cache[key] = (now, result)
    return result.copy() if result else None
```

The `.copy()` call is important — without it, callers could mutate the cached dict and corrupt future lookups.

## Atomic Balance Deduction

This is the most critical function in the entire codebase. Race conditions here mean giving away free service or double-charging customers. The pattern uses `BEGIN IMMEDIATE` for pessimistic locking:

```python
def deduct(key: str, amount: float, endpoint: str = "") -> bool:
    """Atomically deduct amount. Returns False if insufficient funds."""
    if amount < 0:
        return False
    
    # Check daily spend limit first
    allowed, _remaining = check_daily_spend(key, amount)
    if not allowed:
        return False

    now = datetime.now(timezone.utc).isoformat()
    c = sqlite3.connect(DB_PATH, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    try:
        c.execute("BEGIN IMMEDIATE")
        cur = c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd - ?, "
            "total_spent = total_spent + ?, "
            "call_count = call_count + 1, last_used_at = ? "
            "WHERE key = ? AND is_active = 1 AND balance_usd >= ?",
            (amount, amount, now, key, amount),
        )
        if cur.rowcount > 0:
            c.execute("COMMIT")
            _key_cache.pop(key, None)  # Invalidate cache
            return True
        else:
            c.execute("COMMIT")
            return False
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
```

The magic is in the `WHERE ... AND balance_usd >= ?` clause. The balance check and deduction happen in a single atomic UPDATE. If two requests race, only one will succeed — the other gets `rowcount == 0` and returns False.

Note: we use `isolation_level=None` and manual `BEGIN IMMEDIATE` instead of the context manager. This gives us explicit control over the transaction boundary.

## Tiered Rate Limiting

Different key balances get different rate limits. This incentivizes customers to top up:

```python
def get_key_tier(key: str) -> str:
    """Determine tier: free (20/min), starter (60), pro (120), enterprise (300)."""
    with _conn() as c:
        row = c.execute(
            "SELECT balance_usd, subscription_tier FROM api_keys "
            "WHERE key = ? AND is_active = 1", (key,),
        ).fetchone()
    if not row:
        return "free"
    
    # Subscription tier takes priority
    sub_tier = row["subscription_tier"]
    if sub_tier:
        return {"hobby": "starter", "pro": "pro",
                "business": "enterprise"}.get(sub_tier, "starter")
    
    # Otherwise, tier by balance
    bal = row["balance_usd"]
    if bal >= 10.0:
        return "enterprise"
    if bal >= 2.0:
        return "pro"
    return "starter"

TIER_LIMITS = {"free": 20, "starter": 60, "pro": 120, "enterprise": 300}
```

## Daily Spend Limits

Protect customers from accidental overspending. Default is $10/day, configurable up to $50:

```python
def check_daily_spend(key: str, amount: float) -> tuple[bool, float]:
    """Check if adding amount would exceed daily limit.
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
    return (spent + amount) <= limit, limit - spent
```

## Key Rotation

When a key is compromised, the customer needs a new key without losing their balance. Key rotation deactivates the old key and creates a new one in a single transaction:

```python
def rotate_key(old_key: str) -> dict | None:
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
        now = datetime.now(timezone.utc).isoformat()
        
        c.execute("UPDATE api_keys SET is_active = 0 WHERE key = ?", (old_key,))
        c.execute(
            "INSERT INTO api_keys (key, label, balance_usd, ...) VALUES (...)",
            (new_key, row["label"], row["balance_usd"], ...),
        )
        c.execute("COMMIT")
        return {"new_key": new_key, "balance_usd": row["balance_usd"]}
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
```

## The Middleware Pattern

Protect your endpoints with a decorator that validates the key and deducts credits:

```python
# In helpers.py
from functools import wraps
from flask import request, jsonify

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        key = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
        if not key:
            key = request.args.get("api_key", "")
        if not key:
            return jsonify({"error": "API key required"}), 401
        
        info = validate_key(key)
        if not info:
            return jsonify({"error": "Invalid or inactive API key"}), 401
        
        request.api_key = key
        return f(*args, **kwargs)
    return decorated
```

## Exercise

1. Create `api_keys.py` with the schema, `generate_key`, `validate_key`, and `deduct` functions.
2. Create a `/generate-key` endpoint that returns a new key with $0.10 trial credits.
3. Create a protected endpoint using `@require_api_key` that deducts $0.01 per call.
4. Test: generate a key, call the endpoint 10 times, verify the balance decreases.
5. Test the race condition: send 20 concurrent requests with only $0.10 balance and verify no overdraft.

Next lesson: connecting Stripe so customers can actually pay you.
