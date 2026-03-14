"""Prepaid API key management. Keys funded upfront, deducted per call."""
import hashlib
import sqlite3
import os
import secrets
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "api_keys.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
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
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_referral ON api_keys(referral_code)")


def generate_key(initial_balance: float = 0.0, label: str = "", source: str = "unknown") -> dict:
    key = "apk_" + secrets.token_urlsafe(32)
    referral_code = hashlib.sha256(key.encode()).hexdigest()[:8]
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO api_keys (key, label, balance_usd, created_at, source, referral_code) VALUES (?, ?, ?, ?, ?, ?)",
            (key, label, initial_balance, now, source, referral_code),
        )
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
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd + ?, last_used_at = ? WHERE key = ? AND is_active = 1",
            (amount, now, key),
        )
        row = c.execute("SELECT balance_usd FROM api_keys WHERE key = ?", (key,)).fetchone()
    if not row:
        return {"error": "key_not_found"}
    return {"key": key, "balance_usd": row["balance_usd"], "topped_up": amount}


def get_key_status(key: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT key, label, balance_usd, total_spent, call_count, is_active, created_at, last_used_at, source, first_used_at, referral_code FROM api_keys WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def validate_key(key: str) -> dict | None:
    """Lightweight check — returns key record if active, None otherwise."""
    with _conn() as c:
        row = c.execute(
            "SELECT key, balance_usd, is_active FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
    return dict(row) if row else None


def deduct(key: str, amount: float) -> bool:
    """Atomically deduct amount from key balance. Returns False if insufficient funds."""
    now = datetime.utcnow().isoformat()
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
        c.execute("COMMIT")
        return cur.rowcount > 0
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def deduct_metered(key: str, input_tokens: int, output_tokens: int,
                   input_rate: float, output_rate: float) -> dict | None:
    """Deduct actual token cost from key balance. Returns cost info or None if insufficient.

    Rates are USD per million tokens.
    """
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT balance_usd FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
        if not row or row["balance_usd"] < cost:
            return None
        c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd - ?, total_spent = total_spent + ?, "
            "call_count = call_count + 1, last_used_at = ?, "
            "first_used_at = CASE WHEN first_used_at IS NULL THEN ? ELSE first_used_at END "
            "WHERE key = ?",
            (cost, cost, now, now, key),
        )
        new_balance = c.execute(
            "SELECT balance_usd FROM api_keys WHERE key = ?", (key,),
        ).fetchone()["balance_usd"]
    return {"cost": round(cost, 8), "balance_remaining": round(new_balance, 8)}
