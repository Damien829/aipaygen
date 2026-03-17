#!/usr/bin/env python3
"""
Self-Healing Security Monitor — run from cron every 10 minutes.

Checks:
- IPs with > 50 requests in last 10 minutes (potential scraping)
- IPs hitting premium endpoints without API keys (potential abuse)
- Auto-adds suspicious IPs to a temporary block list
- Writes alerts to alerts.db

Usage: python3 security_monitor.py
"""
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

ALERTS_DB = os.path.join(SCRIPT_DIR, "alerts.db")
FUNNEL_DB = os.path.join(SCRIPT_DIR, "funnel.db")
ACCESS_LOG = os.path.join(SCRIPT_DIR, "access.log")

# Thresholds
SCRAPING_THRESHOLD = 50          # requests in 10 min
PREMIUM_ABUSE_THRESHOLD = 10     # premium hits without key in 10 min
TEMP_BLOCK_DURATION = 3600       # 1 hour temporary block

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SECURITY] %(levelname)s %(message)s",
)
log = logging.getLogger("security_monitor")


def _init_alerts_db():
    """Create alerts table if it doesn't exist."""
    with sqlite3.connect(ALERTS_DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS security_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT NOT NULL,
            ip TEXT DEFAULT '',
            details TEXT DEFAULT '{}',
            action_taken TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type ON security_alerts(alert_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_created ON security_alerts(created_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS temp_blocklist (
            ip TEXT PRIMARY KEY,
            reason TEXT DEFAULT '',
            blocked_until TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")


def _log_alert(alert_type: str, ip: str = "", details: dict = None, action: str = ""):
    """Write a security alert to alerts.db."""
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(ALERTS_DB) as conn:
        conn.execute(
            "INSERT INTO security_alerts (alert_type, ip, details, action_taken, created_at) VALUES (?, ?, ?, ?, ?)",
            (alert_type, ip, json.dumps(details or {}), action, now),
        )
    log.warning("ALERT [%s] ip=%s action=%s details=%s", alert_type, ip, action, details)


def _add_temp_block(ip: str, reason: str, duration: int = TEMP_BLOCK_DURATION):
    """Add an IP to the temporary block list."""
    now = datetime.utcnow()
    blocked_until = (now + timedelta(seconds=duration)).isoformat()
    with sqlite3.connect(ALERTS_DB) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO temp_blocklist (ip, reason, blocked_until, created_at) VALUES (?, ?, ?, ?)",
            (ip, reason, blocked_until, now.isoformat()),
        )
    log.info("BLOCKED ip=%s reason=%s until=%s", ip, reason, blocked_until)


def _cleanup_expired_blocks():
    """Remove expired entries from temp_blocklist."""
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(ALERTS_DB) as conn:
        deleted = conn.execute("DELETE FROM temp_blocklist WHERE blocked_until < ?", (now,)).rowcount
        if deleted:
            log.info("Cleaned up %d expired temp blocks", deleted)


def check_scraping_abuse():
    """Check for IPs with > 50 requests in last 10 minutes from funnel events."""
    if not os.path.exists(FUNNEL_DB):
        log.info("No funnel.db found, skipping scraping check")
        return 0

    cutoff = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
    alerts = 0
    with sqlite3.connect(FUNNEL_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT ip, COUNT(*) as cnt FROM funnel_events
               WHERE created_at > ? AND ip != '' AND ip != '127.0.0.1'
               GROUP BY ip HAVING cnt > ?""",
            (cutoff, SCRAPING_THRESHOLD),
        ).fetchall()
        for row in rows:
            ip = row["ip"]
            count = row["cnt"]
            _log_alert("scraping_suspected", ip=ip, details={"requests_10min": count}, action="temp_blocked")
            _add_temp_block(ip, f"scraping: {count} requests in 10min")
            alerts += 1
    return alerts


def check_premium_abuse():
    """Check for IPs hitting premium endpoints without API keys."""
    if not os.path.exists(FUNNEL_DB):
        return 0

    cutoff = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
    alerts = 0
    with sqlite3.connect(FUNNEL_DB) as conn:
        conn.row_factory = sqlite3.Row
        # Look for repeated 402_shown events — indicates hitting premium without paying
        rows = conn.execute(
            """SELECT ip, COUNT(*) as cnt FROM funnel_events
               WHERE event_type = '402_shown' AND created_at > ?
               AND ip != '' AND ip != '127.0.0.1'
               GROUP BY ip HAVING cnt > ?""",
            (cutoff, PREMIUM_ABUSE_THRESHOLD),
        ).fetchall()
        for row in rows:
            ip = row["ip"]
            count = row["cnt"]
            _log_alert("premium_abuse", ip=ip, details={"402_count_10min": count}, action="temp_blocked")
            _add_temp_block(ip, f"premium_abuse: {count} x 402 in 10min")
            alerts += 1
    return alerts


def check_free_tier_abuse():
    """Check for IPs that hit free_tier_exhausted many times (trying to bypass limits)."""
    if not os.path.exists(FUNNEL_DB):
        return 0

    cutoff = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
    alerts = 0
    with sqlite3.connect(FUNNEL_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT ip, COUNT(*) as cnt FROM funnel_events
               WHERE event_type = 'free_tier_exhausted' AND created_at > ?
               AND ip != '' AND ip != '127.0.0.1'
               GROUP BY ip HAVING cnt > ?""",
            (cutoff, PREMIUM_ABUSE_THRESHOLD),
        ).fetchall()
        for row in rows:
            ip = row["ip"]
            count = row["cnt"]
            _log_alert("free_tier_abuse", ip=ip, details={"exhausted_count_10min": count}, action="temp_blocked")
            _add_temp_block(ip, f"free_tier_abuse: {count} exhausted events in 10min")
            alerts += 1
    return alerts


def get_blocked_ips():
    """Return currently blocked IPs (for use by app.py or admin endpoints)."""
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(ALERTS_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ip, reason, blocked_until FROM temp_blocklist WHERE blocked_until > ?",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_alerts(hours: int = 24, limit: int = 50):
    """Return recent security alerts."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with sqlite3.connect(ALERTS_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM security_alerts WHERE created_at > ? ORDER BY created_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def main():
    """Run all security checks."""
    _init_alerts_db()
    _cleanup_expired_blocks()

    total_alerts = 0
    total_alerts += check_scraping_abuse()
    total_alerts += check_premium_abuse()
    total_alerts += check_free_tier_abuse()

    blocked = get_blocked_ips()

    log.info(
        "Security scan complete: %d new alerts, %d IPs currently blocked",
        total_alerts, len(blocked),
    )
    return total_alerts


if __name__ == "__main__":
    main()
