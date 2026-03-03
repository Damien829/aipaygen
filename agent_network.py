"""SQLite-backed agent networking: messaging, shared knowledge base, task board,
free daily tier, agent reputation, and task subscriptions."""
import sqlite3
import json
import uuid
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "agent_network.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_network_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT UNIQUE NOT NULL,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                subject TEXT,
                body TEXT NOT NULL,
                thread_id TEXT,
                read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_to ON agent_messages(to_agent)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_thread ON agent_messages(thread_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id TEXT UNIQUE NOT NULL,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                author_agent TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                upvotes INTEGER DEFAULT 0,
                downvotes INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_kb_topic ON knowledge_base(topic)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS task_board (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                posted_by TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                skills_needed TEXT DEFAULT '[]',
                reward_usd REAL DEFAULT 0.0,
                status TEXT DEFAULT 'open',
                claimed_by TEXT,
                result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON task_board(status)")
        # ── Free daily tier tracking ──────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS free_tier_usage (
                ip TEXT NOT NULL,
                date TEXT NOT NULL,
                calls_used INTEGER DEFAULT 0,
                PRIMARY KEY (ip, date)
            )
        """)
        # ── Agent reputation ──────────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS agent_reputation (
                agent_id TEXT PRIMARY KEY,
                task_completions INTEGER DEFAULT 0,
                knowledge_contributions INTEGER DEFAULT 0,
                upvotes_received INTEGER DEFAULT 0,
                score REAL DEFAULT 0.0,
                last_updated TEXT
            )
        """)
        # ── Task subscriptions (webhook callbacks for new tasks) ──────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS task_subscriptions (
                sub_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                skills TEXT DEFAULT '[]',
                callback_url TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sub_agent ON task_subscriptions(agent_id)")


# ── Messaging ──────────────────────────────────────────────────────────────────

def send_message(from_agent: str, to_agent: str, subject: str, body: str,
                 thread_id: str = None) -> dict:
    msg_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    tid = thread_id or msg_id
    with _conn() as c:
        c.execute(
            "INSERT INTO agent_messages (msg_id, from_agent, to_agent, subject, body, thread_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (msg_id, from_agent, to_agent, subject or "", body, tid, now),
        )
    return {"msg_id": msg_id, "thread_id": tid, "sent": True}


def get_inbox(agent_id: str, unread_only: bool = False) -> list:
    q = "SELECT * FROM agent_messages WHERE to_agent=?"
    params = [agent_id]
    if unread_only:
        q += " AND read=0"
    q += " ORDER BY created_at DESC LIMIT 50"
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def mark_read(msg_id: str, agent_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE agent_messages SET read=1 WHERE msg_id=? AND to_agent=?",
            (msg_id, agent_id)
        )
    return cur.rowcount > 0


def broadcast_message(from_agent: str, subject: str, body: str) -> int:
    """Send to ALL_AGENTS — stored as a single broadcast record."""
    return send_message(from_agent, "__broadcast__", subject, body)


# ── Knowledge Base ─────────────────────────────────────────────────────────────

def add_knowledge(topic: str, content: str, author_agent: str,
                  tags: list = None, entry_id: str = None) -> dict:
    eid = entry_id or str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    tags_str = json.dumps(tags or [])
    with _conn() as c:
        existing = c.execute("SELECT id FROM knowledge_base WHERE entry_id=?", (eid,)).fetchone()
        if existing:
            c.execute(
                "UPDATE knowledge_base SET topic=?, content=?, author_agent=?, tags=? WHERE entry_id=?",
                (topic, content, author_agent, tags_str, eid)
            )
        else:
            c.execute(
                "INSERT INTO knowledge_base (entry_id, topic, content, author_agent, tags, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, topic, content, author_agent, tags_str, now),
            )
    update_reputation(author_agent, knowledge_added=True)
    return {"entry_id": eid, "added": True}


def search_knowledge(query: str, limit: int = 10) -> list:
    q = f"%{query.lower()}%"
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM knowledge_base WHERE LOWER(topic) LIKE ? OR LOWER(content) LIKE ? OR LOWER(tags) LIKE ? "
            "ORDER BY upvotes DESC, created_at DESC LIMIT ?",
            (q, q, q, limit)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("tags") or "[]")
        result.append(d)
    return result


def get_trending_topics(limit: int = 10) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT topic, COUNT(*) as entry_count, SUM(upvotes) as total_votes "
            "FROM knowledge_base GROUP BY topic ORDER BY entry_count DESC, total_votes DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def vote_knowledge(entry_id: str, up: bool = True) -> dict:
    col = "upvotes" if up else "downvotes"
    with _conn() as c:
        c.execute(f"UPDATE knowledge_base SET {col}={col}+1 WHERE entry_id=?", (entry_id,))
        row = c.execute(
            "SELECT upvotes, downvotes, author_agent FROM knowledge_base WHERE entry_id=?",
            (entry_id,)
        ).fetchone()
    if not row:
        return {"error": "not found"}
    if up:
        update_reputation(row["author_agent"], upvote_received=True)
    return {"entry_id": entry_id, "upvotes": row["upvotes"], "downvotes": row["downvotes"]}


# ── Task Board ─────────────────────────────────────────────────────────────────

def submit_task(posted_by: str, title: str, description: str,
                skills_needed: list = None, reward_usd: float = 0.0) -> dict:
    task_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    skills_str = json.dumps(skills_needed or [])
    with _conn() as c:
        c.execute(
            "INSERT INTO task_board (task_id, posted_by, title, description, skills_needed, reward_usd, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, posted_by, title, description, skills_str, reward_usd, now, now),
        )
    # Notify subscribers in background
    import threading
    threading.Thread(
        target=_notify_task_subscribers,
        args=(task_id, title, description, skills_needed or [], reward_usd),
        daemon=True
    ).start()
    return {"task_id": task_id, "submitted": True}


def browse_tasks(status: str = "open", skill: str = None, limit: int = 20) -> list:
    q = "SELECT * FROM task_board WHERE status=?"
    params = [status]
    if skill:
        q += " AND LOWER(skills_needed) LIKE ?"
        params.append(f"%{skill.lower()}%")
    q += " ORDER BY reward_usd DESC, created_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["skills_needed"] = json.loads(d.get("skills_needed") or "[]")
        result.append(d)
    return result


def claim_task(task_id: str, agent_id: str) -> bool:
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        cur = c.execute(
            "UPDATE task_board SET status='claimed', claimed_by=?, updated_at=? WHERE task_id=? AND status='open'",
            (agent_id, now, task_id)
        )
    return cur.rowcount > 0


def complete_task(task_id: str, agent_id: str, result: str) -> bool:
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        cur = c.execute(
            "UPDATE task_board SET status='completed', result=?, updated_at=? "
            "WHERE task_id=? AND claimed_by=?",
            (result, now, task_id, agent_id)
        )
    if cur.rowcount > 0:
        update_reputation(agent_id, task_done=True)
    return cur.rowcount > 0


def get_task(task_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM task_board WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["skills_needed"] = json.loads(d.get("skills_needed") or "[]")
    return d


# ── Free Daily Tier ────────────────────────────────────────────────────────────

FREE_DAILY_LIMIT = 10


def check_and_use_free_tier(ip: str) -> bool:
    """Returns True and increments counter if this IP has free calls remaining today."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with _conn() as c:
        row = c.execute(
            "SELECT calls_used FROM free_tier_usage WHERE ip=? AND date=?", (ip, today)
        ).fetchone()
        used = row["calls_used"] if row else 0
        if used >= FREE_DAILY_LIMIT:
            return False
        if row:
            c.execute(
                "UPDATE free_tier_usage SET calls_used=calls_used+1 WHERE ip=? AND date=?",
                (ip, today)
            )
        else:
            c.execute(
                "INSERT INTO free_tier_usage (ip, date, calls_used) VALUES (?, ?, 1)",
                (ip, today)
            )
    return True


def get_free_tier_status(ip: str) -> dict:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with _conn() as c:
        row = c.execute(
            "SELECT calls_used FROM free_tier_usage WHERE ip=? AND date=?", (ip, today)
        ).fetchone()
    used = row["calls_used"] if row else 0
    return {
        "ip": ip,
        "calls_used_today": used,
        "daily_limit": FREE_DAILY_LIMIT,
        "remaining": max(0, FREE_DAILY_LIMIT - used),
        "resets_at": "midnight UTC",
        "note": "Free tier applies to all paid AI endpoints. Top up with /buy-credits for unlimited access.",
    }


# ── Agent Reputation ───────────────────────────────────────────────────────────

def update_reputation(agent_id: str, task_done: bool = False,
                       knowledge_added: bool = False, upvote_received: bool = False):
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute("""
            INSERT INTO agent_reputation (agent_id, task_completions, knowledge_contributions, upvotes_received, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                task_completions = task_completions + ?,
                knowledge_contributions = knowledge_contributions + ?,
                upvotes_received = upvotes_received + ?,
                last_updated = ?
        """, (
            agent_id, int(task_done), int(knowledge_added), int(upvote_received), now,
            int(task_done), int(knowledge_added), int(upvote_received), now,
        ))
        row = c.execute("SELECT * FROM agent_reputation WHERE agent_id=?", (agent_id,)).fetchone()
        if row:
            score = (row["task_completions"] * 3.0 +
                     row["knowledge_contributions"] * 1.5 +
                     row["upvotes_received"] * 0.5)
            c.execute("UPDATE agent_reputation SET score=? WHERE agent_id=?", (score, agent_id))


def get_reputation(agent_id: str) -> dict:
    with _conn() as c:
        row = c.execute("SELECT * FROM agent_reputation WHERE agent_id=?", (agent_id,)).fetchone()
    if not row:
        return {
            "agent_id": agent_id, "score": 0.0,
            "task_completions": 0, "knowledge_contributions": 0, "upvotes_received": 0,
        }
    return dict(row)


def get_leaderboard(limit: int = 20) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM agent_reputation ORDER BY score DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Task Subscriptions ─────────────────────────────────────────────────────────

def subscribe_tasks(agent_id: str, skills: list, callback_url: str) -> dict:
    sub_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute("DELETE FROM task_subscriptions WHERE agent_id=?", (agent_id,))
        c.execute(
            "INSERT INTO task_subscriptions (sub_id, agent_id, skills, callback_url, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sub_id, agent_id, json.dumps(skills), callback_url, now),
        )
    return {"sub_id": sub_id, "agent_id": agent_id, "subscribed": True,
            "skills_filter": skills or "all tasks"}


def get_task_subscribers(agent_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM task_subscriptions WHERE agent_id=?", (agent_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["skills"] = json.loads(d.get("skills") or "[]")
    return d


def _notify_task_subscribers(task_id: str, title: str, description: str,
                              skills_needed: list, reward_usd: float):
    """Internal: find matching subscribers and POST notification."""
    import requests as _req
    with _conn() as c:
        rows = c.execute("SELECT * FROM task_subscriptions").fetchall()
    for r in rows:
        d = dict(r)
        sub_skills = json.loads(d.get("skills") or "[]")
        # Match: subscriber has no skill filter OR overlap with task skills
        if not sub_skills or not skills_needed or \
                any(s.lower() in [sk.lower() for sk in skills_needed] for s in sub_skills):
            try:
                _req.post(d["callback_url"], json={
                    "event": "new_task",
                    "task_id": task_id,
                    "title": title,
                    "description": description,
                    "skills_needed": skills_needed,
                    "reward_usd": reward_usd,
                    "claim_url": f"https://api.aipaygent.xyz/task/claim",
                }, timeout=5)
            except Exception:
                pass
