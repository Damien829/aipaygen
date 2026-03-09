"""Conversion funnel tracking — append-only SQLite event logger."""
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "funnel.db")

# IPs to exclude from tracking (localhost / cron noise)
_IGNORE_IPS = {"127.0.0.1", "::1", "localhost", ""}


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_funnel_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS funnel_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                endpoint TEXT DEFAULT '',
                ip TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_type ON funnel_events(event_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_created ON funnel_events(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_created_type ON funnel_events(created_at, event_type)")


def log_event(event_type: str, endpoint: str = "", ip: str = "", metadata: str = "{}"):
    """Append a funnel event. Types: 402_shown, discover_hit, llms_txt_hit, credits_bought, key_generated, mcp_free_exhausted"""
    if ip in _IGNORE_IPS:
        return
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO funnel_events (event_type, endpoint, ip, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (event_type, endpoint, ip, metadata, now),
        )


def get_funnel_stats(days: int = 7) -> dict:
    """Get funnel event counts grouped by type for the last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT event_type, COUNT(*) as count FROM funnel_events WHERE created_at >= ? GROUP BY event_type ORDER BY count DESC",
            (cutoff,),
        ).fetchall()
        total = c.execute(
            "SELECT COUNT(*) as total FROM funnel_events WHERE created_at >= ?", (cutoff,)
        ).fetchone()["total"]
        daily = c.execute(
            "SELECT date(created_at) as day, event_type, COUNT(*) as count "
            "FROM funnel_events WHERE created_at >= ? GROUP BY day, event_type ORDER BY day DESC",
            (cutoff,),
        ).fetchall()
    return {
        "period_days": days,
        "total_events": total,
        "by_type": {r["event_type"]: r["count"] for r in rows},
        "daily": [dict(r) for r in daily],
    }


# Auto-init on import
init_funnel_db()
