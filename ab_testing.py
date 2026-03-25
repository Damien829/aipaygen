"""Simple A/B testing framework — deterministic split tests with SQLite tracking."""
import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

_log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "ab_tests.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.row_factory = sqlite3.Row
    return c


def init_ab_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS ab_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT NOT NULL,
                variant TEXT NOT NULL,
                visitor_id TEXT NOT NULL,
                event TEXT NOT NULL DEFAULT 'page_view',
                converted INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ab_test ON ab_events(test_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ab_test_variant ON ab_events(test_name, variant)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ab_visitor ON ab_events(test_name, visitor_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ab_created ON ab_events(created_at)")


def get_variant(test_name: str, visitor_id: str) -> str:
    """Return 'A' or 'B' deterministically based on hash of test_name + visitor_id."""
    if not visitor_id:
        return "A"
    h = hashlib.md5(f"{test_name}:{visitor_id}".encode()).hexdigest()
    return "B" if int(h, 16) % 2 == 1 else "A"


def track_event(test_name: str, variant: str, visitor_id: str, event: str = "page_view", converted: bool = False):
    """Record an A/B test event."""
    if not test_name or not visitor_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO ab_events (test_name, variant, visitor_id, event, converted, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (test_name, variant, visitor_id, event, 1 if converted else 0, now),
            )
    except Exception:
        _log.exception("Failed to track A/B event")


def track_conversion(test_name: str, variant: str, visitor_id: str, event: str = "conversion"):
    """Shortcut: record a conversion event."""
    track_event(test_name, variant, visitor_id, event=event, converted=True)


def get_test_results(test_name: str, days: int = 30) -> dict:
    """Return A vs B stats with conversion rates for a given test."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    results = {"test_name": test_name, "period_days": days, "variants": {}}

    with _conn() as c:
        for variant in ("A", "B"):
            # Unique visitors
            visitors = c.execute(
                "SELECT COUNT(DISTINCT visitor_id) as cnt FROM ab_events WHERE test_name = ? AND variant = ? AND created_at >= ?",
                (test_name, variant, cutoff),
            ).fetchone()["cnt"]

            # Total events by type
            events = c.execute(
                "SELECT event, COUNT(*) as cnt FROM ab_events WHERE test_name = ? AND variant = ? AND created_at >= ? GROUP BY event",
                (test_name, variant, cutoff),
            ).fetchall()
            event_counts = {r["event"]: r["cnt"] for r in events}

            # Conversions (any event with converted=1)
            conversions = c.execute(
                "SELECT COUNT(DISTINCT visitor_id) as cnt FROM ab_events WHERE test_name = ? AND variant = ? AND converted = 1 AND created_at >= ?",
                (test_name, variant, cutoff),
            ).fetchone()["cnt"]

            conv_rate = round(100 * conversions / visitors, 2) if visitors > 0 else 0.0

            results["variants"][variant] = {
                "visitors": visitors,
                "conversions": conversions,
                "conversion_rate": conv_rate,
                "events": event_counts,
            }

    # Determine winner
    a = results["variants"].get("A", {})
    b = results["variants"].get("B", {})
    a_rate = a.get("conversion_rate", 0)
    b_rate = b.get("conversion_rate", 0)
    if a.get("visitors", 0) < 30 or b.get("visitors", 0) < 30:
        results["winner"] = "insufficient_data"
        results["confidence"] = "low"
    elif a_rate > b_rate:
        results["winner"] = "A"
        results["lift"] = round(a_rate - b_rate, 2)
    elif b_rate > a_rate:
        results["winner"] = "B"
        results["lift"] = round(b_rate - a_rate, 2)
    else:
        results["winner"] = "tie"
        results["lift"] = 0

    return results


def list_tests(days: int = 30) -> list:
    """List all active tests with basic stats."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT test_name, COUNT(DISTINCT visitor_id) as visitors, COUNT(*) as events, "
            "SUM(converted) as conversions, MIN(created_at) as started "
            "FROM ab_events WHERE created_at >= ? GROUP BY test_name ORDER BY events DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


# Auto-init on import
init_ab_db()
