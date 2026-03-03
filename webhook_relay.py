"""Webhook relay — agents get a unique URL to receive webhooks from external services."""
import sqlite3
import uuid
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "webhook_relay.db")
MAX_EVENTS_PER_WEBHOOK = 500


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_webhooks_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS webhooks (
                webhook_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                label TEXT,
                secret TEXT,
                event_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_event_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_wh_agent ON webhooks(agent_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                event_id TEXT PRIMARY KEY,
                webhook_id TEXT NOT NULL,
                method TEXT NOT NULL,
                headers TEXT NOT NULL,
                body TEXT,
                source_ip TEXT,
                received_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_whe_hook ON webhook_events(webhook_id)")


def create_webhook(agent_id: str, label: str = None) -> dict:
    webhook_id = str(uuid.uuid4()).replace("-", "")[:16]
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO webhooks (webhook_id, agent_id, label, created_at) VALUES (?, ?, ?, ?)",
            (webhook_id, agent_id, label or f"webhook-{webhook_id[:6]}", now),
        )
    return {
        "webhook_id": webhook_id,
        "receive_url": f"https://api.aipaygent.xyz/webhooks/{webhook_id}/receive",
        "events_url": f"https://api.aipaygent.xyz/webhooks/{webhook_id}/events",
        "label": label or f"webhook-{webhook_id[:6]}",
        "created_at": now,
        "note": "POST any payload to receive_url. Events are stored for 7 days.",
    }


def receive_webhook_event(webhook_id: str, method: str, headers: dict,
                          body: str, source_ip: str) -> dict:
    """Record an incoming webhook event."""
    with _conn() as c:
        hook = c.execute("SELECT * FROM webhooks WHERE webhook_id=?", (webhook_id,)).fetchone()
    if not hook:
        return None
    event_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    # Keep only safe headers (strip auth headers)
    safe_headers = {k: v for k, v in headers.items()
                    if k.lower() not in ("authorization", "cookie", "x-api-key")}
    with _conn() as c:
        c.execute(
            "INSERT INTO webhook_events (event_id, webhook_id, method, headers, body, source_ip, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, webhook_id, method, json.dumps(safe_headers), body, source_ip, now),
        )
        c.execute(
            "UPDATE webhooks SET event_count=event_count+1, last_event_at=? WHERE webhook_id=?",
            (now, webhook_id),
        )
        # Prune old events
        c.execute(
            "DELETE FROM webhook_events WHERE webhook_id=? AND event_id NOT IN "
            "(SELECT event_id FROM webhook_events WHERE webhook_id=? ORDER BY received_at DESC LIMIT ?)",
            (webhook_id, webhook_id, MAX_EVENTS_PER_WEBHOOK),
        )
    return {"event_id": event_id, "received": True}


def get_webhook_events(webhook_id: str, limit: int = 50) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM webhook_events WHERE webhook_id=? ORDER BY received_at DESC LIMIT ?",
            (webhook_id, min(limit, 200)),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["headers"] = json.loads(d["headers"])
        except Exception:
            pass
        try:
            d["body"] = json.loads(d["body"])
        except Exception:
            pass
        result.append(d)
    return result


def list_webhooks(agent_id: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT webhook_id, label, event_count, created_at, last_event_at "
            "FROM webhooks WHERE agent_id=? ORDER BY created_at DESC",
            (agent_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["receive_url"] = f"https://api.aipaygent.xyz/webhooks/{d['webhook_id']}/receive"
        d["events_url"] = f"https://api.aipaygent.xyz/webhooks/{d['webhook_id']}/events"
        result.append(d)
    return result


def get_webhook(webhook_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM webhooks WHERE webhook_id=?", (webhook_id,)).fetchone()
    return dict(row) if row else None
