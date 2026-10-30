"""Workflow and marketplace database."""
import sqlite3
import os
import json
import logging
from datetime import datetime

_log = logging.getLogger(__name__)
_DB_PATH = os.path.join(os.path.dirname(__file__), "workflows.db")


def _connect():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_workflow_db():
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_wallet TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            steps TEXT NOT NULL DEFAULT '[]',
            category TEXT NOT NULL DEFAULT 'general',
            is_public INTEGER NOT NULL DEFAULT 0,
            price_usdc REAL NOT NULL DEFAULT 0.0,
            run_count INTEGER NOT NULL DEFAULT 0,
            avg_rating REAL NOT NULL DEFAULT 0.0,
            rating_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS workflow_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            rater_wallet TEXT NOT NULL,
            stars INTEGER NOT NULL CHECK(stars >= 1 AND stars <= 5),
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (workflow_id) REFERENCES workflows(id),
            UNIQUE(workflow_id, rater_wallet)
        );
        CREATE TABLE IF NOT EXISTS workflow_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            buyer_wallet TEXT NOT NULL,
            price_usdc REAL NOT NULL,
            creator_share REAL NOT NULL,
            platform_share REAL NOT NULL,
            tx_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (workflow_id) REFERENCES workflows(id)
        );
        CREATE INDEX IF NOT EXISTS idx_workflows_public ON workflows(is_public, category);
        CREATE INDEX IF NOT EXISTS idx_workflows_creator ON workflows(creator_wallet);
        CREATE INDEX IF NOT EXISTS idx_ratings_workflow ON workflow_ratings(workflow_id);
    """)
    conn.close()
    _log.info("workflow DB initialized at %s", _DB_PATH)


def create_workflow(creator_wallet, name, description, steps, category="general"):
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO workflows (creator_wallet, name, description, steps, category) VALUES (?, ?, ?, ?, ?)",
        (creator_wallet, name, description, json.dumps(steps), category),
    )
    wf_id = cur.lastrowid
    conn.commit()
    conn.close()
    return wf_id


def get_workflow(wf_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["steps"] = json.loads(d["steps"])
    return d


def list_user_workflows(creator_wallet):
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM workflows WHERE creator_wallet=? ORDER BY updated_at DESC", (creator_wallet,)
    ).fetchall()
    conn.close()
    return [_parse_row(r) for r in rows]


def update_workflow(wf_id, creator_wallet, **kwargs):
    conn = _connect()
    row = conn.execute("SELECT creator_wallet FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if not row or row["creator_wallet"] != creator_wallet:
        conn.close()
        return False
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in ("name", "description", "steps", "category", "is_public", "price_usdc"):
            sets.append(f"{k}=?")
            vals.append(json.dumps(v) if k == "steps" else v)
    if not sets:
        conn.close()
        return False
    sets.append("updated_at=datetime('now')")
    vals.append(wf_id)
    conn.execute(f"UPDATE workflows SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return True


def delete_workflow(wf_id, creator_wallet):
    conn = _connect()
    conn.execute("DELETE FROM workflows WHERE id=? AND creator_wallet=?", (wf_id, creator_wallet))
    conn.commit()
    conn.close()


def increment_run_count(wf_id):
    conn = _connect()
    conn.execute("UPDATE workflows SET run_count=run_count+1 WHERE id=?", (wf_id,))
    conn.commit()
    conn.close()


def list_marketplace(category=None, sort="popular", limit=20, offset=0):
    conn = _connect()
    query = "SELECT * FROM workflows WHERE is_public=1"
    params = []
    if category:
        query += " AND category=?"
        params.append(category)
    if sort == "popular":
        query += " ORDER BY run_count DESC"
    elif sort == "rating":
        query += " ORDER BY avg_rating DESC"
    elif sort == "newest":
        query += " ORDER BY created_at DESC"
    elif sort == "price_low":
        query += " ORDER BY price_usdc ASC"
    query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_parse_row(r) for r in rows]


def rate_workflow(wf_id, rater_wallet, stars, comment=""):
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO workflow_ratings (workflow_id, rater_wallet, stars, comment) VALUES (?, ?, ?, ?)",
        (wf_id, rater_wallet, stars, comment),
    )
    # Update avg rating
    row = conn.execute(
        "SELECT AVG(stars) as avg, COUNT(*) as cnt FROM workflow_ratings WHERE workflow_id=?", (wf_id,)
    ).fetchone()
    conn.execute(
        "UPDATE workflows SET avg_rating=?, rating_count=? WHERE id=?",
        (round(row["avg"], 2), row["cnt"], wf_id),
    )
    conn.commit()
    conn.close()


def record_purchase(wf_id, buyer_wallet, price_usdc, tx_hash=""):
    creator_share = round(price_usdc * 0.70, 6)
    platform_share = round(price_usdc * 0.30, 6)
    conn = _connect()
    conn.execute(
        "INSERT INTO workflow_purchases (workflow_id, buyer_wallet, price_usdc, creator_share, platform_share, tx_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (wf_id, buyer_wallet, price_usdc, creator_share, platform_share, tx_hash),
    )
    conn.commit()
    conn.close()
    return {"creator_share": creator_share, "platform_share": platform_share}


def _parse_row(row):
    d = dict(row)
    if "steps" in d:
        d["steps"] = json.loads(d["steps"])
    return d
