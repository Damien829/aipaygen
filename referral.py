"""Referral / affiliate tracking — agents earn API credits for driving signups."""
import sqlite3
import uuid
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "referral.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_referral_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS ref_clicks (
                click_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                ip TEXT,
                path TEXT,
                user_agent TEXT,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ref_clicks_agent ON ref_clicks(agent_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS ref_conversions (
                conv_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                amount_usd REAL DEFAULT 0.0,
                commission_usd REAL DEFAULT 0.0,
                meta TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ref_conv_agent ON ref_conversions(agent_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS ref_agents (
                agent_id TEXT PRIMARY KEY,
                label TEXT,
                api_key TEXT,
                total_clicks INTEGER DEFAULT 0,
                total_conversions INTEGER DEFAULT 0,
                total_earned_usd REAL DEFAULT 0.0,
                created_at TEXT NOT NULL
            )
        """)


COMMISSION_RATE = 0.10  # 10% of referred purchase


def register_referral_agent(agent_id: str, label: str = None, api_key: str = None) -> dict:
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        existing = c.execute("SELECT * FROM ref_agents WHERE agent_id=?", (agent_id,)).fetchone()
        if existing:
            return dict(existing)
        c.execute(
            "INSERT INTO ref_agents (agent_id, label, api_key, created_at) VALUES (?, ?, ?, ?)",
            (agent_id, label or agent_id, api_key, now),
        )
    return {
        "agent_id": agent_id,
        "referral_url": f"https://api.aipaygen.com/?ref={agent_id}",
        "buy_referral_url": f"https://api.aipaygen.com/buy-credits?ref={agent_id}",
        "commission_rate": f"{int(COMMISSION_RATE * 100)}%",
        "label": label or agent_id,
        "created_at": now,
    }


def record_click(agent_id: str, ip: str, path: str, user_agent: str = "") -> str:
    click_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        # Ensure agent exists
        c.execute(
            "INSERT OR IGNORE INTO ref_agents (agent_id, label, created_at) VALUES (?, ?, ?)",
            (agent_id, agent_id, now),
        )
        c.execute(
            "INSERT INTO ref_clicks (click_id, agent_id, ip, path, user_agent, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (click_id, agent_id, ip, path, user_agent, now),
        )
        c.execute(
            "UPDATE ref_agents SET total_clicks=total_clicks+1 WHERE agent_id=?", (agent_id,)
        )
    return click_id


def record_conversion(agent_id: str, event_type: str, amount_usd: float = 0.0,
                       meta: dict = None) -> dict:
    """Record a conversion (purchase, signup). Credits commission to referring agent's API key."""
    commission = round(amount_usd * COMMISSION_RATE, 4)
    conv_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO ref_conversions (conv_id, agent_id, event_type, amount_usd, commission_usd, meta, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conv_id, agent_id, event_type, amount_usd, commission, json.dumps(meta or {}), now),
        )
        c.execute(
            "UPDATE ref_agents SET total_conversions=total_conversions+1, "
            "total_earned_usd=total_earned_usd+? WHERE agent_id=?",
            (commission, agent_id),
        )
        # Credit commission to agent's API key if they have one
        agent = c.execute("SELECT api_key FROM ref_agents WHERE agent_id=?", (agent_id,)).fetchone()
    if agent and agent["api_key"] and commission > 0:
        try:
            from api_keys import topup_key
            topup_key(agent["api_key"], commission)
        except Exception:
            pass
    return {"conv_id": conv_id, "agent_id": agent_id, "commission_usd": commission}


def get_referral_stats(agent_id: str) -> dict:
    with _conn() as c:
        agent = c.execute("SELECT * FROM ref_agents WHERE agent_id=?", (agent_id,)).fetchone()
        if not agent:
            return {"error": "agent not found", "agent_id": agent_id}
        recent = c.execute(
            "SELECT event_type, amount_usd, commission_usd, created_at FROM ref_conversions "
            "WHERE agent_id=? ORDER BY created_at DESC LIMIT 20",
            (agent_id,)
        ).fetchall()
    d = dict(agent)
    d["recent_conversions"] = [dict(r) for r in recent]
    d["referral_url"] = f"https://api.aipaygen.com/?ref={agent_id}"
    d["commission_rate"] = f"{int(COMMISSION_RATE * 100)}%"
    return d


def get_referral_leaderboard(limit: int = 20) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT agent_id, label, total_clicks, total_conversions, total_earned_usd "
            "FROM ref_agents ORDER BY total_earned_usd DESC, total_clicks DESC LIMIT ?",
            (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["referral_url"] = f"https://api.aipaygen.com/?ref={d['agent_id']}"
        result.append(d)
    return result
