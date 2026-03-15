"""Conversion funnel tracking — append-only SQLite event logger."""
import json as _json
import logging
import re as _re
import sqlite3
import os
from datetime import datetime, timedelta

import requests

_log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "funnel.db")

# IPs to exclude from tracking (localhost / cron noise)
_IGNORE_IPS = {"127.0.0.1", "::1", "localhost", ""}

# ── Bot Detection ─────────────────────────────────────────────────────────────
_BOT_PATTERNS = _re.compile(
    r"(Googlebot|bingbot|Baiduspider|YandexBot|DotBot|AhrefsBot|SemrushBot|"
    r"MJ12bot|PetalBot|facebookexternalhit|Twitterbot|LinkedInBot|Slackbot|Slurp|"
    r"Sogou|Exabot|Applebot|Bytespider|GPTBot|ClaudeBot|CCBot|DataForSeoBot|"
    r"DuckDuckBot|Seekport|serpstatbot|ia_archiver|Screaming Frog|Uptimerobot|pingdom|"
    r"bot|crawl|spider|crawler|scraper|headless|phantom|selenium)",
    _re.IGNORECASE,
)


def is_bot(user_agent: str = "") -> bool:
    """Return True if the User-Agent matches known bot patterns."""
    if not user_agent:
        return False
    return bool(_BOT_PATTERNS.search(user_agent))


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
                is_bot INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_type ON funnel_events(event_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_created ON funnel_events(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_created_type ON funnel_events(created_at, event_type)")
        # Add is_bot column if missing (safe migration)
        try:
            c.execute("ALTER TABLE funnel_events ADD COLUMN is_bot INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists


def log_event(event_type: str, endpoint: str = "", ip: str = "", metadata: str = "{}", user_agent: str = ""):
    """Append a funnel event. Types: 402_shown, discover_hit, llms_txt_hit, credits_bought, key_generated, mcp_free_exhausted"""
    if ip in _IGNORE_IPS:
        return
    # Auto-detect user_agent from Flask request context if not passed
    if not user_agent:
        try:
            from flask import request as _req
            user_agent = _req.headers.get("User-Agent", "")
        except (ImportError, RuntimeError):
            pass
    now = datetime.utcnow().isoformat()
    bot_flag = 1 if is_bot(user_agent) else 0
    with _conn() as c:
        c.execute(
            "INSERT INTO funnel_events (event_type, endpoint, ip, metadata, is_bot, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, endpoint, ip, metadata, bot_flag, now),
        )


def get_funnel_stats(days: int = 7, exclude_bots: bool = True) -> dict:
    """Get funnel event counts grouped by type for the last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    bot_filter = " AND (is_bot IS NULL OR is_bot = 0)" if exclude_bots else ""
    with _conn() as c:
        rows = c.execute(
            f"SELECT event_type, COUNT(*) as count FROM funnel_events WHERE created_at >= ?{bot_filter} GROUP BY event_type ORDER BY count DESC LIMIT 1000",
            (cutoff,),
        ).fetchall()
        total = c.execute(
            f"SELECT COUNT(*) as total FROM funnel_events WHERE created_at >= ?{bot_filter}", (cutoff,)
        ).fetchone()["total"]
        daily = c.execute(
            f"SELECT date(created_at) as day, event_type, COUNT(*) as count "
            f"FROM funnel_events WHERE created_at >= ?{bot_filter} GROUP BY day, event_type ORDER BY day DESC",
            (cutoff,),
        ).fetchall()
        # Bot stats
        bot_total = c.execute(
            "SELECT COUNT(*) as total FROM funnel_events WHERE created_at >= ? AND is_bot = 1", (cutoff,)
        ).fetchone()["total"]
        unique_ips = c.execute(
            f"SELECT COUNT(DISTINCT ip) as cnt FROM funnel_events WHERE created_at >= ? {bot_filter}", (cutoff,)
        ).fetchone()["cnt"]
    return {
        "period_days": days,
        "total_events": total,
        "bot_events": bot_total,
        "unique_ips": unique_ips,
        "by_type": {r["event_type"]: r["count"] for r in rows},
        "daily": [dict(r) for r in daily],
    }


def get_analytics(days: int = 7) -> dict:
    """Extended analytics: total vs bot events, unique IPs, funnel conversion."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) as cnt FROM funnel_events WHERE created_at >= ?", (cutoff,)
        ).fetchone()["cnt"]
        bot_total = c.execute(
            "SELECT COUNT(*) as cnt FROM funnel_events WHERE created_at >= ? AND is_bot = 1", (cutoff,)
        ).fetchone()["cnt"]
        unique_ips = c.execute(
            "SELECT COUNT(DISTINCT ip) as cnt FROM funnel_events WHERE created_at >= ? AND is_bot = 0",
            (cutoff,),
        ).fetchone()["cnt"]
        # Funnel conversion stages (non-bot only)
        funnel_stages = ["discover_hit", "catalog_browse", "demo_used", "key_generated", "credits_bought"]
        funnel = {}
        for stage in funnel_stages:
            row = c.execute(
                "SELECT COUNT(*) as cnt FROM funnel_events WHERE created_at >= ? AND is_bot = 0 AND event_type = ?",
                (cutoff, stage),
            ).fetchone()
            funnel[stage] = row["cnt"]
    return {
        "period_days": days,
        "total_events": total,
        "bot_events": bot_total,
        "human_events": total - bot_total,
        "unique_ips_human": unique_ips,
        "funnel": funnel,
    }


def poll_pypi_downloads():
    """Fetch PyPI download stats for aipaygen-mcp and log as funnel event (call daily)."""
    try:
        r = requests.get("https://pypistats.org/api/packages/aipaygen-mcp/recent", timeout=10)
        if r.status_code != 200:
            return
        data = r.json().get("data", {})
        log_event(
            "mcp_pypi_downloads",
            ip="cron",
            metadata=_json.dumps({
                "last_day": data.get("last_day", 0),
                "last_week": data.get("last_week", 0),
                "last_month": data.get("last_month", 0),
            }),
        )
        _log.info("PyPI downloads: day=%s week=%s month=%s",
                   data.get("last_day"), data.get("last_week"), data.get("last_month"))
    except Exception:
        _log.exception("PyPI download poll failed")


# Auto-init on import
init_funnel_db()
