"""Persistent agent sessions with context accumulation and call history."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            tool TEXT NOT NULL,
            input TEXT NOT NULL,
            output TEXT NOT NULL,
            time_ms INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_calls_sid ON session_calls(session_id)")
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
    # Check if session has expired based on TTL
    now = datetime.now(timezone.utc)
    try:
        last_active = datetime.fromisoformat(row["last_active"].replace("Z", "+00:00"))
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)
        if now - last_active > timedelta(hours=row["ttl_hours"]):
            # Session expired — clean it up and return None
            conn.execute("DELETE FROM session_calls WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return None
    except (ValueError, TypeError):
        pass  # If timestamp parsing fails, allow the session
    now_iso = now.isoformat()
    conn.execute("UPDATE sessions SET last_active = ? WHERE id = ?", (now_iso, session_id))
    conn.commit()
    return {
        "session_id": row["id"],
        "agent_id": row["agent_id"],
        "context": json.loads(row["context"]),
        "created_at": row["created_at"],
        "last_active": now_iso,
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


def delete_session(session_id):
    """Delete a session and all its call history."""
    conn = _get_conn()
    conn.execute("DELETE FROM session_calls WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()


def add_session_call(session_id, tool, input_data, output_data, time_ms=0):
    """Record a tool call in the session history."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO session_calls (session_id, tool, input, output, time_ms, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, tool, json.dumps(input_data), json.dumps(output_data), time_ms, now),
    )
    conn.execute("UPDATE sessions SET last_active = ? WHERE id = ?", (now, session_id))
    conn.commit()


def get_session_history(session_id, limit=50):
    """Return call history for a session, ordered chronologically."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT tool, input, output, time_ms, created_at FROM session_calls WHERE session_id = ? ORDER BY id ASC LIMIT ?",
        (session_id, min(limit, 200)),
    ).fetchall()
    return [
        {
            "tool": r["tool"],
            "input": json.loads(r["input"]),
            "output": json.loads(r["output"]),
            "time_ms": r["time_ms"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def get_session_context_messages(session_id, limit=10):
    """Build conversation-style context from recent calls for AI tool injection."""
    history = get_session_history(session_id, limit=limit)
    messages = []
    for call in history:
        out_summary = call["output"].get("result") or call["output"].get("summary") or str(call["output"])[:300]
        messages.append(f"[Previous call] Tool: {call['tool']}, Result: {out_summary}")
    return "\n".join(messages)


def cleanup_expired():
    conn = _get_conn()
    conn.execute(
        "DELETE FROM session_calls WHERE session_id IN "
        "(SELECT id FROM sessions WHERE datetime(last_active, '+' || ttl_hours || ' hours') < datetime('now'))"
    )
    conn.execute(
        "DELETE FROM sessions WHERE datetime(last_active, '+' || ttl_hours || ' hours') < datetime('now')"
    )
    conn.commit()


# Auto-init on import
init_sessions_db()
