"""Alerting system — tracks service issues and sends notifications."""
import os
import sqlite3
import time
import logging
import threading

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "alerts.db")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
_consecutive_failures = 0
_alert_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.row_factory = sqlite3.Row
    return c


def init_alerts_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                resolved_at REAL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type)")


def create_alert(alert_type: str, severity: str, message: str):
    """Create an alert and optionally send email."""
    try:
        # Deduplicate: don't create same alert_type if one exists unresolved in last hour
        with _conn() as c:
            recent = c.execute(
                "SELECT id FROM alerts WHERE alert_type = ? AND resolved = 0 AND timestamp > ?",
                (alert_type, time.time() - 3600),
            ).fetchone()
            if recent:
                return  # Already have an active alert of this type

            c.execute(
                "INSERT INTO alerts (timestamp, alert_type, severity, message) VALUES (?, ?, ?, ?)",
                (time.time(), alert_type, severity, message),
            )
        logger.warning("ALERT [%s] %s: %s", severity, alert_type, message)
        _send_alert_email(alert_type, severity, message)
    except Exception as e:
        logger.error("Failed to create alert: %s", e)


def resolve_alert(alert_type: str):
    """Resolve all open alerts of a given type."""
    try:
        with _conn() as c:
            c.execute(
                "UPDATE alerts SET resolved = 1, resolved_at = ? WHERE alert_type = ? AND resolved = 0",
                (time.time(), alert_type),
            )
    except Exception:
        pass


def get_recent_alerts(limit: int = 20, include_resolved: bool = False) -> list[dict]:
    """Return recent alerts."""
    try:
        with _conn() as c:
            if include_resolved:
                rows = c.execute(
                    "SELECT id, timestamp, alert_type, severity, message, resolved, resolved_at "
                    "FROM alerts ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT id, timestamp, alert_type, severity, message, resolved, resolved_at "
                    "FROM alerts WHERE resolved = 0 ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def process_health_result(status: str, checks: dict, response_time_ms: float):
    """Evaluate a health check result and fire alerts as needed."""
    global _consecutive_failures

    with _alert_lock:
        if status == "down":
            _consecutive_failures += 1
            if _consecutive_failures >= 3:
                create_alert("service_down", "critical", f"Service down {_consecutive_failures} consecutive checks")
        elif status == "ok":
            if _consecutive_failures >= 3:
                resolve_alert("service_down")
            _consecutive_failures = 0
        else:
            # degraded — don't reset counter but don't increment either
            pass

    # Response time alert
    if response_time_ms > 5000:
        create_alert("slow_response", "warning", f"Health check response time {response_time_ms:.0f}ms exceeds 5s threshold")
    elif response_time_ms < 3000:
        resolve_alert("slow_response")

    # Disk space alert
    disk_free = checks.get("disk_free_mb")
    if isinstance(disk_free, (int, float)) and disk_free < 500:
        create_alert("low_disk", "critical", f"Disk space critically low: {disk_free:.0f}MB remaining")
    elif isinstance(disk_free, (int, float)) and disk_free >= 1000:
        resolve_alert("low_disk")

    # Memory usage alert
    mem_pct = checks.get("memory_used_pct")
    if isinstance(mem_pct, (int, float)) and mem_pct > 90:
        create_alert("high_memory", "warning", f"Memory usage at {mem_pct:.1f}%")
    elif isinstance(mem_pct, (int, float)) and mem_pct < 80:
        resolve_alert("high_memory")

    # Database alerts
    for key, val in checks.items():
        if key.startswith("db_") and isinstance(val, str) and val.startswith("error"):
            create_alert(f"db_{key}", "critical", f"Database check failed: {key} — {val}")
        elif key.startswith("db_") and val == "ok":
            resolve_alert(f"db_{key}")


def _send_alert_email(alert_type: str, severity: str, message: str):
    """Send alert email via Resend if configured."""
    if not ADMIN_EMAIL:
        return
    try:
        import resend
        if not resend.api_key:
            return
        severity_emoji = {"critical": "!!!", "warning": "!!", "info": "i"}.get(severity, "")
        resend.Emails.send({
            "from": "AiPayGen Alerts <noreply@aipaygen.com>",
            "to": [ADMIN_EMAIL],
            "subject": f"[{severity.upper()}] AiPayGen Alert: {alert_type}",
            "html": f"""<div style="font-family:monospace;padding:20px;background:#1a1a1a;color:#e8e8e8;">
                <h2 style="color:{'#ff4444' if severity == 'critical' else '#ffb800'};">{severity_emoji} {alert_type}</h2>
                <p>{message}</p>
                <p style="color:#888;font-size:0.85rem;">Sent from AiPayGen monitoring at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}</p>
            </div>""",
        })
    except Exception as e:
        logger.debug("Alert email failed: %s", e)


def cleanup_old_alerts(days: int = 30):
    """Delete resolved alerts older than N days."""
    cutoff = time.time() - (days * 86400)
    try:
        with _conn() as c:
            c.execute("DELETE FROM alerts WHERE resolved = 1 AND timestamp < ?", (cutoff,))
    except Exception:
        pass


init_alerts_db()
