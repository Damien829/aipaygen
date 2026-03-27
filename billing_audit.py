"""Billing audit log — every billing event recorded for dispute resolution."""
import sqlite3
import os
import hashlib
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "billing_audit.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.row_factory = sqlite3.Row
    return c


def init_audit_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS billing_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                api_key_masked TEXT NOT NULL,
                amount_usd REAL DEFAULT 0.0,
                balance_after REAL DEFAULT 0.0,
                endpoint TEXT DEFAULT '',
                ip_hash TEXT DEFAULT '',
                metadata TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_key ON billing_audit(api_key_masked)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_type ON billing_audit(event_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON billing_audit(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_key_type ON billing_audit(api_key_masked, event_type)")


def _mask_key(key: str) -> str:
    """Mask API key for audit log: apk_xxxx...yyyy"""
    if not key or len(key) < 12:
        return key or "unknown"
    return key[:8] + "..." + key[-4:]


def _hash_ip(ip: str) -> str:
    return hashlib.sha256((ip or "unknown").encode()).hexdigest()[:16]


def log_audit(event_type: str, api_key: str = "", amount_usd: float = 0.0,
              balance_after: float = 0.0, endpoint: str = "", ip: str = "",
              metadata: str = ""):
    """Log a billing event. Event types: deduction, topup, key_generated,
    key_rotated, key_deactivated, trial_credits, stripe_payment, x402_payment."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO billing_audit (event_type, api_key_masked, amount_usd, "
                "balance_after, endpoint, ip_hash, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_type, _mask_key(api_key), amount_usd, balance_after,
                 endpoint, _hash_ip(ip), metadata, now),
            )
    except Exception as e:
        import logging
        logging.getLogger("billing_audit").error("AUDIT WRITE FAILED [%s] key=%s amt=%.4f: %s",
                                                  event_type, _mask_key(api_key), amount_usd, e)


def get_audit_log(api_key_masked: str = "", event_type: str = "",
                  limit: int = 50) -> list[dict]:
    """Query audit log. Filter by masked key or event type."""
    with _conn() as c:
        if api_key_masked and event_type:
            rows = c.execute(
                "SELECT * FROM billing_audit WHERE api_key_masked = ? AND event_type = ? "
                "ORDER BY id DESC LIMIT ?",
                (api_key_masked, event_type, limit),
            ).fetchall()
        elif api_key_masked:
            rows = c.execute(
                "SELECT * FROM billing_audit WHERE api_key_masked = ? ORDER BY id DESC LIMIT ?",
                (api_key_masked, limit),
            ).fetchall()
        elif event_type:
            rows = c.execute(
                "SELECT * FROM billing_audit WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM billing_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


# Auto-init on import
init_audit_db()
