# eas_reputation.py
"""On-chain reputation attestations via Ethereum Attestation Service on Base."""
import os
import json
import sqlite3
from datetime import datetime

# Base Mainnet EAS contract
EAS_CONTRACT = "0x4200000000000000000000000000000000000021"
SCHEMA_REGISTRY = "0x4200000000000000000000000000000000000020"

# Our reputation schema UID (register once, then hardcode)
REPUTATION_SCHEMA_UID = os.environ.get("EAS_SCHEMA_UID", "")

BASE_RPC = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")

_DB_PATH = os.path.join(os.path.dirname(__file__), "eas_reputation.db")


def _conn():
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_eas_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS attestation_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_wallet TEXT NOT NULL,
                attestation_type TEXT NOT NULL,
                score INTEGER NOT NULL,
                details TEXT DEFAULT '',
                status TEXT DEFAULT 'queued',
                tx_hash TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                submitted_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_eas_wallet ON attestation_queue(agent_wallet)")


def create_reputation_attestation(
    agent_wallet: str,
    attestation_type: str,
    score: int,
    details: str = "",
) -> dict | None:
    """Queue an EAS attestation for agent reputation.

    Types: "task_completed", "upvote", "service_rating"
    Score: 1-5
    Returns attestation record or None if invalid.
    """
    if not agent_wallet or attestation_type not in ("task_completed", "upvote", "service_rating"):
        return None
    score = max(1, min(5, score))
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO attestation_queue (agent_wallet, attestation_type, score, details, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_wallet, attestation_type, score, details, now),
        )
        row_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {
        "id": row_id,
        "agent": agent_wallet,
        "type": attestation_type,
        "score": score,
        "details": details,
        "status": "queued",
    }


def get_reputation_attestations(agent_wallet: str) -> list[dict]:
    """Get all queued/submitted attestations for an agent."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM attestation_queue WHERE agent_wallet = ? ORDER BY created_at DESC",
            (agent_wallet,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_reputation_summary(agent_wallet: str) -> dict:
    """Aggregate reputation score for an agent."""
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) as total, AVG(score) as avg_score, SUM(CASE WHEN attestation_type='task_completed' THEN 1 ELSE 0 END) as tasks "
            "FROM attestation_queue WHERE agent_wallet = ?",
            (agent_wallet,),
        ).fetchone()
    return {
        "agent": agent_wallet,
        "total_attestations": row["total"],
        "average_score": round(row["avg_score"], 2) if row["avg_score"] else 0,
        "tasks_completed": row["tasks"],
    }


def get_pending_attestations(limit: int = 50) -> list[dict]:
    """Get attestations ready for batch submission to EAS."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM attestation_queue WHERE status = 'queued' ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_submitted(attestation_ids: list[int], tx_hash: str):
    """Mark attestations as submitted with tx hash."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        placeholders = ",".join("?" * len(attestation_ids))
        c.execute(
            f"UPDATE attestation_queue SET status = 'submitted', tx_hash = ?, submitted_at = ? WHERE id IN ({placeholders})",
            [tx_hash, now] + attestation_ids,
        )
