"""In-app notification system. SQLite-backed, per API key."""
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "notifications.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.row_factory = sqlite3.Row
    return c


def init_notifications_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_notif_key ON notifications(api_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_notif_unread ON notifications(api_key, read)")


def create_notification(api_key: str, event_type: str, message: str):
    """Insert a notification for the given API key."""
    if not api_key:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO notifications (api_key, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                (api_key, event_type, message, now),
            )
    except Exception:
        pass


def get_unread(api_key: str, limit: int = 20) -> list[dict]:
    """Return unread notifications and mark them as read."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, event_type, message, created_at FROM notifications "
            "WHERE api_key = ? AND read = 0 ORDER BY id DESC LIMIT ?",
            (api_key, limit),
        ).fetchall()
        results = [dict(r) for r in rows]
        if results:
            ids = [r["id"] for r in results]
            placeholders = ",".join("?" * len(ids))
            c.execute(f"UPDATE notifications SET read = 1 WHERE id IN ({placeholders})", ids)
    return results


def broadcast(event_type: str, message: str):
    """Send a notification to every API key in the system."""
    try:
        keys_db = os.path.join(os.path.dirname(__file__), "api_keys.db")
        kc = sqlite3.connect(keys_db)
        rows = kc.execute("SELECT key FROM api_keys").fetchall()
        kc.close()
        for row in rows:
            create_notification(row[0], event_type, message)
        return len(rows)
    except Exception:
        return 0


# Auto-init on import
init_notifications_db()
