"""Persistent key-value memory store for AI agents, backed by SQLite."""
import sqlite3
import json
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "agent_memory.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.row_factory = sqlite3.Row
    return c


def init_memory_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                tags TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(agent_id, key)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_agent ON agent_memory(agent_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS agent_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT UNIQUE NOT NULL,
                name TEXT,
                description TEXT,
                capabilities TEXT,
                endpoint TEXT,
                registered_at TEXT,
                last_seen TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS marketplace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT UNIQUE NOT NULL,
                agent_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                endpoint TEXT NOT NULL,
                price_usd REAL NOT NULL,
                category TEXT,
                capabilities TEXT,
                call_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        try:
            c.execute("ALTER TABLE marketplace ADD COLUMN wallet_address TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # Column already exists
        c.execute("CREATE INDEX IF NOT EXISTS idx_mp_category ON marketplace(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mp_active ON marketplace(is_active)")

        # Extended marketplace columns (safe — ignores if exists)
        for col, typedef in [
            ("pricing_models", "TEXT DEFAULT '{}'"),
            ("tags", "TEXT DEFAULT '[]'"),
            ("is_featured", "INTEGER DEFAULT 0"),
            ("total_revenue", "REAL DEFAULT 0.0"),
            ("subscriber_count", "INTEGER DEFAULT 0"),
            ("performance_metrics", "TEXT DEFAULT '{}'"),
            ("avg_rating", "REAL DEFAULT 0.0"),
            ("review_count", "INTEGER DEFAULT 0"),
        ]:
            try:
                c.execute(f"ALTER TABLE marketplace ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass

        try:
            c.execute("ALTER TABLE marketplace ADD COLUMN is_verified INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Reviews table
        c.execute("""CREATE TABLE IF NOT EXISTS marketplace_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT UNIQUE NOT NULL,
            listing_id TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
            review_text TEXT DEFAULT '',
            verified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_reviews_listing ON marketplace_reviews(listing_id)")

        # Subscriptions table
        c.execute("""CREATE TABLE IF NOT EXISTS marketplace_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_id TEXT UNIQUE NOT NULL,
            listing_id TEXT NOT NULL,
            subscriber_id TEXT NOT NULL,
            plan_type TEXT NOT NULL,
            price_usd REAL NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            expires_at TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_subs_listing ON marketplace_subscriptions(listing_id)")

        # Performance time-series
        c.execute("""CREATE TABLE IF NOT EXISTS agent_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            recorded_at TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_perf_listing ON agent_performance(listing_id)")

        init_payment_splits_table()


def memory_set(agent_id: str, key: str, value, tags: list = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    val_str = json.dumps(value) if not isinstance(value, str) else value
    tags_str = json.dumps(tags or [])
    with _conn() as c:
        c.execute("""
            INSERT INTO agent_memory (agent_id, key, value, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, key) DO UPDATE SET value=excluded.value,
                tags=excluded.tags, updated_at=excluded.updated_at
        """, (agent_id, key, val_str, tags_str, now, now))
    return {"agent_id": agent_id, "key": key, "stored": True}


def memory_get(agent_id: str, key: str):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM agent_memory WHERE agent_id=? AND key=?", (agent_id, key)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["value"] = json.loads(d["value"])
    except Exception:
        pass
    d["tags"] = json.loads(d.get("tags") or "[]")
    return d


def memory_list(agent_id: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT key, tags, updated_at FROM agent_memory WHERE agent_id=? ORDER BY updated_at DESC",
            (agent_id,)
        ).fetchall()
    return [{"key": r["key"], "tags": json.loads(r["tags"] or "[]"), "updated_at": r["updated_at"]} for r in rows]


def memory_search(agent_id: str, query: str) -> list:
    """Simple substring search over keys and values."""
    q = f"%{query.lower()}%"
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM agent_memory WHERE agent_id=? AND (LOWER(key) LIKE ? OR LOWER(value) LIKE ?)",
            (agent_id, q, q)
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["value"] = json.loads(d["value"])
        except Exception:
            pass
        results.append(d)
    return results


def memory_delete(agent_id: str, key: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM agent_memory WHERE agent_id=? AND key=?", (agent_id, key))
    return cur.rowcount > 0


def memory_clear(agent_id: str) -> int:
    with _conn() as c:
        cur = c.execute("DELETE FROM agent_memory WHERE agent_id=?", (agent_id,))
    return cur.rowcount


def register_agent(agent_id: str, name: str, description: str,
                   capabilities: list, endpoint: str = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    caps_str = json.dumps(capabilities)
    with _conn() as c:
        c.execute("""
            INSERT INTO agent_registry (agent_id, name, description, capabilities, endpoint, registered_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET name=excluded.name, description=excluded.description,
                capabilities=excluded.capabilities, endpoint=excluded.endpoint, last_seen=excluded.last_seen
        """, (agent_id, name, description, caps_str, endpoint, now, now))
    return {"agent_id": agent_id, "registered": True}


def list_agents() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM agent_registry ORDER BY last_seen DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["capabilities"] = json.loads(d.get("capabilities") or "[]")
        result.append(d)
    return result


# ── Agent Marketplace ─────────────────────────────────────────────────────────

import uuid as _uuid


def marketplace_list_service(agent_id: str, name: str, description: str,
                              endpoint: str, price_usd: float,
                              category: str = "general",
                              capabilities: list = None,
                              wallet_address: str = "",
                              pricing_models: dict = None,
                              tags: list = None) -> dict:
    """Register/update a service in the agent marketplace."""
    now = datetime.now(timezone.utc).isoformat()
    caps_str = json.dumps(capabilities or [])
    pricing_str = json.dumps(pricing_models or {})
    tags_str = json.dumps(tags or [])
    listing_id = str(_uuid.uuid4())
    with _conn() as c:
        existing = c.execute(
            "SELECT listing_id FROM marketplace WHERE agent_id=? AND name=?",
            (agent_id, name)
        ).fetchone()
        if existing:
            listing_id = existing["listing_id"]
            c.execute("""
                UPDATE marketplace SET description=?, endpoint=?, price_usd=?,
                    category=?, capabilities=?, wallet_address=?, pricing_models=?,
                    tags=?, is_active=1, updated_at=?
                WHERE listing_id=?
            """, (description, endpoint, price_usd, category, caps_str,
                  wallet_address, pricing_str, tags_str, now, listing_id))
        else:
            c.execute("""
                INSERT INTO marketplace (listing_id, agent_id, name, description, endpoint,
                    price_usd, category, capabilities, wallet_address, pricing_models,
                    tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (listing_id, agent_id, name, description, endpoint,
                  price_usd, category, caps_str, wallet_address, pricing_str,
                  tags_str, now, now))
    return {"listing_id": listing_id, "listed": True}


def marketplace_get_services(category: str = None, max_price: float = None,
                              min_price: float = None, page: int = 1,
                              per_page: int = 20) -> tuple:
    """Return (list, total) of active marketplace listings."""
    query = "SELECT * FROM marketplace WHERE is_active=1"
    params = []
    if category:
        query += " AND category=?"
        params.append(category)
    if max_price is not None:
        query += " AND price_usd<=?"
        params.append(max_price)
    if min_price is not None:
        query += " AND price_usd>=?"
        params.append(min_price)
    count_q = query.replace("SELECT *", "SELECT COUNT(*)")
    query += " ORDER BY call_count DESC, created_at DESC LIMIT ? OFFSET ?"
    params_paginated = params + [per_page, (page - 1) * per_page]
    with _conn() as c:
        total = c.execute(count_q, params).fetchone()[0]
        rows = c.execute(query, params_paginated).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["capabilities"] = json.loads(d.get("capabilities") or "[]")
        result.append(d)
    return result, total


def marketplace_get_service(listing_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM marketplace WHERE listing_id=?", (listing_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["capabilities"] = json.loads(d.get("capabilities") or "[]")
    return d


def marketplace_increment_calls(listing_id: str):
    with _conn() as c:
        c.execute("UPDATE marketplace SET call_count=call_count+1 WHERE listing_id=?", (listing_id,))


def marketplace_deregister(listing_id: str, agent_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE marketplace SET is_active=0 WHERE listing_id=? AND agent_id=?",
            (listing_id, agent_id)
        )
    return cur.rowcount > 0


# ── Enhanced Marketplace Functions ────────────────────────────────────────────

def marketplace_search(query="", category=None, max_price=None, min_price=None,
                       sort="popular", page=1, per_page=20):
    """Full-text search across agent names, descriptions, capabilities, and tags."""
    conditions = ["is_active = 1"]
    params = []
    if query:
        conditions.append("(name LIKE ? OR description LIKE ? OR capabilities LIKE ? OR tags LIKE ?)")
        q = f"%{query}%"
        params.extend([q, q, q, q])
    if category:
        conditions.append("category = ?")
        params.append(category)
    if max_price is not None:
        conditions.append("price_usd <= ?")
        params.append(max_price)
    if min_price is not None:
        conditions.append("price_usd >= ?")
        params.append(min_price)
    where = " AND ".join(conditions)
    sort_sql = {
        "popular": "call_count DESC",
        "newest": "created_at DESC",
        "price_low": "price_usd ASC",
        "price_high": "price_usd DESC",
        "rating": "avg_rating DESC",
    }.get(sort, "call_count DESC")
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM marketplace WHERE {where}", params).fetchone()[0]
        offset = (page - 1) * per_page
        rows = c.execute(
            f"SELECT * FROM marketplace WHERE {where} ORDER BY {sort_sql} LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()
    return [dict(r) for r in rows], total


def marketplace_verify_agent(listing_id, verified=True):
    """Mark an agent as verified."""
    with _conn() as c:
        c.execute("UPDATE marketplace SET is_verified = ? WHERE listing_id = ?", (1 if verified else 0, listing_id))
    return {"listing_id": listing_id, "verified": verified}


def marketplace_get_categories():
    """Return category counts for active listings."""
    with _conn() as c:
        rows = c.execute(
            "SELECT category, COUNT(*) FROM marketplace WHERE is_active = 1 GROUP BY category ORDER BY COUNT(*) DESC"
        ).fetchall()
    return dict(rows)


def marketplace_add_review(listing_id, reviewer_id, rating, review_text="", verified=False):
    """Add a review and update avg rating on the listing."""
    now = datetime.now(timezone.utc).isoformat()
    review_id = str(_uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO marketplace_reviews (review_id, listing_id, reviewer_id, rating, review_text, verified, created_at) VALUES (?,?,?,?,?,?,?)",
            (review_id, listing_id, reviewer_id, rating, review_text, 1 if verified else 0, now)
        )
        row = c.execute("SELECT AVG(rating), COUNT(*) FROM marketplace_reviews WHERE listing_id = ?", (listing_id,)).fetchone()
        avg, count = row[0], row[1]
        c.execute("UPDATE marketplace SET avg_rating = ?, review_count = ? WHERE listing_id = ?",
                  (round(avg, 2), count, listing_id))
    return {"review_id": review_id, "rating": rating, "listing_id": listing_id}


def marketplace_get_reviews(listing_id, limit=20):
    """Get reviews for a listing."""
    with _conn() as c:
        rows = c.execute(
            "SELECT review_id, reviewer_id, rating, review_text, verified, created_at FROM marketplace_reviews WHERE listing_id = ? ORDER BY created_at DESC LIMIT ?",
            (listing_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def marketplace_record_performance(listing_id, metric_name, metric_value):
    """Record a performance metric data point."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("INSERT INTO agent_performance (listing_id, metric_name, metric_value, recorded_at) VALUES (?,?,?,?)",
                  (listing_id, metric_name, metric_value, now))


def marketplace_get_performance(listing_id, metric_name=None, limit=100):
    """Get performance history for a listing."""
    with _conn() as c:
        if metric_name:
            rows = c.execute(
                "SELECT metric_name, metric_value, recorded_at FROM agent_performance WHERE listing_id = ? AND metric_name = ? ORDER BY recorded_at DESC LIMIT ?",
                (listing_id, metric_name, limit)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT metric_name, metric_value, recorded_at FROM agent_performance WHERE listing_id = ? ORDER BY recorded_at DESC LIMIT ?",
                (listing_id, limit)
            ).fetchall()
    return [dict(r) for r in rows]


def marketplace_leaderboard(category=None, sort="call_count", limit=20):
    """Get top agents by category or overall."""
    conditions = ["is_active = 1"]
    params = []
    if category:
        conditions.append("category = ?")
        params.append(category)
    where = " AND ".join(conditions)
    sort_col = {"call_count": "call_count", "rating": "avg_rating", "revenue": "total_revenue"}.get(sort, "call_count")
    with _conn() as c:
        rows = c.execute(
            f"SELECT listing_id, agent_id, name, category, price_usd, call_count, avg_rating, review_count, total_revenue, pricing_models, tags FROM marketplace WHERE {where} ORDER BY {sort_col} DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    return [dict(r) for r in rows]


# ── Payment Splits (95/5) ────────────────────────────────────────────────────

def init_payment_splits_table():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS payment_splits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT NOT NULL,
                seller_wallet TEXT NOT NULL,
                seller_amount REAL NOT NULL,
                platform_fee REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)

def queue_seller_payment(seller_wallet: str, seller_amount: float, platform_fee: float, listing_id: str) -> dict:
    """Queue a payment split for later settlement."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO payment_splits (listing_id, seller_wallet, seller_amount, platform_fee, created_at) VALUES (?, ?, ?, ?, ?)",
            (listing_id, seller_wallet, seller_amount, platform_fee, now),
        )
    return {"seller_wallet": seller_wallet, "seller_amount": seller_amount, "platform_fee": platform_fee, "status": "pending"}

def get_pending_payments(limit: int = 100) -> list[dict]:
    """Get pending payment splits for batch settlement."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM payment_splits WHERE status = 'pending' ORDER BY created_at LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
