"""Persistent agent sessions with context accumulation."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

SESSIONS_DB = os.environ.get("SESSIONS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions.db"))

_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(SESSIONS_DB, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.row_factory = sqlite3.Row
    return _conn


def init_sessions_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            context TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            last_active TEXT NOT NULL,
            ttl_hours INTEGER DEFAULT 24
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions(agent_id)")
    conn.commit()


def create_session(agent_id, context=None, ttl_hours=24):
    conn = _get_conn()
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    ctx = json.dumps(context if context is not None else {})
    conn.execute(
        "INSERT INTO sessions (id, agent_id, context, created_at, last_active, ttl_hours) VALUES (?, ?, ?, ?, ?, ?)",
        (sid, agent_id, ctx, now, now, ttl_hours),
    )
    conn.commit()
    return sid


def get_session(session_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE sessions SET last_active = ? WHERE id = ?", (now, session_id))
    conn.commit()
    return {
        "session_id": row["id"],
        "agent_id": row["agent_id"],
        "context": json.loads(row["context"]),
        "created_at": row["created_at"],
        "last_active": now,
        "ttl_hours": row["ttl_hours"],
    }


def update_session_context(session_id, context):
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE sessions SET context = ?, last_active = ? WHERE id = ?",
        (json.dumps(context), now, session_id),
    )
    conn.commit()


def cleanup_expired():
    conn = _get_conn()
    conn.execute(
        "DELETE FROM sessions WHERE datetime(last_active, '+' || ttl_hours || ' hours') < datetime('now')"
    )
    conn.commit()


# Auto-init on import
init_sessions_db()
