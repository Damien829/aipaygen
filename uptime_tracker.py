"""Uptime tracker — records health check results in SQLite, provides uptime stats."""
import os
import sqlite3
import time
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "uptime.db")


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


def init_uptime_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS uptime_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                status TEXT NOT NULL,
                response_time_ms REAL NOT NULL,
                checks_passed INTEGER NOT NULL,
                checks_total INTEGER NOT NULL,
                details TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_uptime_ts ON uptime_checks(timestamp)")


def record_check(status: str, response_time_ms: float, checks_passed: int, checks_total: int, details: str = ""):
    """Record a health check result."""
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO uptime_checks (timestamp, status, response_time_ms, checks_passed, checks_total, details) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), status, response_time_ms, checks_passed, checks_total, details),
            )
    except Exception as e:
        logger.warning("Failed to record uptime check: %s", e)


def get_uptime_stats() -> dict:
    """Return uptime percentages for 24h, 7d, 30d windows."""
    now = time.time()
    windows = {
        "24h": now - 86400,
        "7d": now - 86400 * 7,
        "30d": now - 86400 * 30,
    }
    result = {}
    try:
        with _conn() as c:
            for label, cutoff in windows.items():
                total = c.execute(
                    "SELECT COUNT(*) FROM uptime_checks WHERE timestamp >= ?", (cutoff,)
                ).fetchone()[0]
                ok = c.execute(
                    "SELECT COUNT(*) FROM uptime_checks WHERE timestamp >= ? AND status = 'ok'", (cutoff,)
                ).fetchone()[0]
                if total > 0:
                    result[label] = {"uptime_pct": round(ok / total * 100, 2), "total_checks": total, "ok_checks": ok}
                else:
                    result[label] = {"uptime_pct": 100.0, "total_checks": 0, "ok_checks": 0}
    except Exception:
        for label in windows:
            result[label] = {"uptime_pct": 0, "total_checks": 0, "ok_checks": 0}
    return result


def get_recent_checks(limit: int = 50) -> list[dict]:
    """Return most recent health check records."""
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT timestamp, status, response_time_ms, checks_passed, checks_total "
                "FROM uptime_checks ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def cleanup_old_records(days: int = 90):
    """Delete uptime records older than N days."""
    cutoff = time.time() - (days * 86400)
    try:
        with _conn() as c:
            c.execute("DELETE FROM uptime_checks WHERE timestamp < ?", (cutoff,))
    except Exception:
        pass


init_uptime_db()
