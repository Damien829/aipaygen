"""Webhook registration and event dispatch for API key holders."""

import json
import logging
import os
import sqlite3
import threading
import time

import requests

logger = logging.getLogger(__name__)

_DB_PATH = os.environ.get("WEBHOOKS_DB") or os.path.join(os.path.dirname(__file__), "webhook_dispatch.db")
_shared_conn = None  # used for :memory: databases


def _get_conn():
    global _shared_conn
    if _DB_PATH == ":memory:":
        if _shared_conn is None:
            _shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            _shared_conn.row_factory = sqlite3.Row
        return _shared_conn
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _close_conn(conn):
    if _DB_PATH != ":memory:":
        conn.close()


def init_webhooks_dispatch_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT NOT NULL,
            url TEXT NOT NULL,
            events TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uw_api_key ON user_webhooks(api_key)")
    conn.commit()
    _close_conn(conn)


def register_webhook(api_key, url, events):
    """Register a webhook. Returns ID or None if URL is not HTTPS."""
    if not url or not url.startswith("https://"):
        return None
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO user_webhooks (api_key, url, events) VALUES (?, ?, ?)",
        (api_key, url, json.dumps(events)),
    )
    conn.commit()
    wh_id = cur.lastrowid
    _close_conn(conn)
    return wh_id


def list_webhooks(api_key):
    conn = _get_conn()
    rows = conn.execute("SELECT id, api_key, url, events, created_at FROM user_webhooks WHERE api_key = ?", (api_key,)).fetchall()
    _close_conn(conn)
    return [{"id": r["id"], "url": r["url"], "events": json.loads(r["events"]), "created_at": r["created_at"]} for r in rows]


def delete_webhook(webhook_id, api_key):
    conn = _get_conn()
    cur = conn.execute("DELETE FROM user_webhooks WHERE id = ? AND api_key = ?", (webhook_id, api_key))
    conn.commit()
    deleted = cur.rowcount > 0
    _close_conn(conn)
    return deleted


def dispatch_event(event_type, api_key, payload=None):
    """Dispatch event to matching webhooks in a background thread."""
    def _dispatch():
        try:
            conn = _get_conn()
            rows = conn.execute("SELECT id, url, events FROM user_webhooks WHERE api_key = ?", (api_key,)).fetchall()
            _close_conn(conn)
            for row in rows:
                events = json.loads(row["events"])
                if event_type not in events:
                    continue
                body = {"event": event_type, "api_key": api_key, "payload": payload or {}}
                backoff = [1, 2, 4]
                for attempt, wait in enumerate(backoff):
                    try:
                        resp = requests.post(row["url"], json=body, timeout=10)
                        if resp.status_code < 500:
                            break
                    except Exception:
                        pass
                    if attempt < len(backoff) - 1:
                        time.sleep(wait)
        except Exception as e:
            logger.error("dispatch_event error: %s", e)

    threading.Thread(target=_dispatch, daemon=True).start()


# Auto-init on import
init_webhooks_dispatch_db()
