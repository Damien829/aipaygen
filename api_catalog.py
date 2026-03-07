"""SQLite catalog for discovered APIs."""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "api_catalog.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS discovered_apis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                base_url TEXT UNIQUE NOT NULL,
                docs_url TEXT,
                auth_required INTEGER DEFAULT 0,
                auth_type TEXT,
                category TEXT,
                source TEXT,
                quality_score REAL DEFAULT 0,
                price_usd REAL DEFAULT 0,
                sample_endpoint TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS discovery_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                apis_found INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',
                error TEXT
            )
        """)
    _migrate_schema()


def _migrate_schema():
    """Add columns introduced after initial deployment."""
    with _conn() as c:
        existing = {r[1] for r in c.execute("PRAGMA table_info(discovered_apis)").fetchall()}
        new_cols = [
            ("x402_compatible", "INTEGER DEFAULT 0"),
            ("total_calls", "INTEGER DEFAULT 0"),
            ("total_revenue_usd", "REAL DEFAULT 0"),
            ("total_cost_usd", "REAL DEFAULT 0"),
            ("last_health_check", "TEXT"),
            ("health_status", "TEXT DEFAULT 'unknown'"),
            ("avg_latency_ms", "REAL"),
            ("openapi_url", "TEXT"),
        ]
        for col, typedef in new_cols:
            if col not in existing:
                c.execute(f"ALTER TABLE discovered_apis ADD COLUMN {col} {typedef}")


def record_api_economics(api_id: int, revenue: float, cost: float):
    """Track revenue and cost per catalog API call."""
    with _conn() as c:
        c.execute(
            "UPDATE discovered_apis SET "
            "total_calls = COALESCE(total_calls, 0) + 1, "
            "total_revenue_usd = COALESCE(total_revenue_usd, 0) + ?, "
            "total_cost_usd = COALESCE(total_cost_usd, 0) + ? "
            "WHERE id = ?",
            (revenue, cost, api_id),
        )


def upsert_api(**kwargs) -> int:
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        existing = c.execute(
            "SELECT id FROM discovered_apis WHERE base_url = ?", (kwargs.get("base_url"),)
        ).fetchone()
        if existing:
            kwargs["updated_at"] = now
            sets = ", ".join(f"{k} = ?" for k in kwargs if k != "base_url")
            vals = [kwargs[k] for k in kwargs if k != "base_url"] + [kwargs["base_url"]]
            c.execute(f"UPDATE discovered_apis SET {sets} WHERE base_url = ?", vals)
            return existing["id"]
        else:
            kwargs.setdefault("created_at", now)
            kwargs.setdefault("updated_at", now)
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" * len(kwargs))
            cur = c.execute(
                f"INSERT INTO discovered_apis ({cols}) VALUES ({placeholders})",
                list(kwargs.values()),
            )
            return cur.lastrowid


def get_all_apis(page=1, per_page=20, category=None, source=None,
                 min_score=None, free_only=False):
    wheres = ["is_active = 1"]
    params = []
    if category:
        wheres.append("category = ?")
        params.append(category)
    if source:
        wheres.append("source = ?")
        params.append(source)
    if min_score is not None:
        wheres.append("quality_score >= ?")
        params.append(min_score)
    if free_only:
        wheres.append("auth_required = 0")

    where_clause = " AND ".join(wheres)
    offset = (page - 1) * per_page

    with _conn() as c:
        total = c.execute(
            f"SELECT COUNT(*) FROM discovered_apis WHERE {where_clause}", params
        ).fetchone()[0]
        rows = c.execute(
            f"SELECT * FROM discovered_apis WHERE {where_clause} "
            f"ORDER BY quality_score DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
    return [dict(r) for r in rows], total


def get_api(api_id) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM discovered_apis WHERE id = ?", (api_id,)).fetchone()
    return dict(row) if row else None


def log_run_start(agent_name: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO discovery_runs (agent_name, started_at, status) VALUES (?, ?, 'running')",
            (agent_name, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def log_run_end(run_id: int, found: int, status: str, error: str = None):
    with _conn() as c:
        c.execute(
            "UPDATE discovery_runs SET completed_at=?, apis_found=?, status=?, error=? WHERE id=?",
            (datetime.utcnow().isoformat(), found, status, error, run_id),
        )


def get_recent_runs(limit=20) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM discovery_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_apis_for_health_check(limit=30) -> list:
    """Get APIs needing health checks (not checked in 24h)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, base_url, sample_endpoint FROM discovered_apis "
            "WHERE is_active = 1 AND (last_health_check IS NULL "
            "OR last_health_check < datetime('now', '-24 hours')) "
            "ORDER BY total_calls DESC, quality_score DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_health(api_id: int, status: str, latency_ms: float = None):
    """Update health status after a check."""
    with _conn() as c:
        c.execute(
            "UPDATE discovered_apis SET health_status = ?, last_health_check = datetime('now'), "
            "avg_latency_ms = COALESCE(?, avg_latency_ms) WHERE id = ?",
            (status, latency_ms, api_id),
        )
        if status == "dead":
            c.execute("UPDATE discovered_apis SET is_active = 0 WHERE id = ?", (api_id,))


def get_catalog_economics() -> dict:
    """Return P&L summary for the admin dashboard."""
    with _conn() as c:
        totals = c.execute(
            "SELECT COALESCE(SUM(total_revenue_usd),0), COALESCE(SUM(total_cost_usd),0), "
            "COALESCE(SUM(total_calls),0) FROM discovered_apis"
        ).fetchone()
        top = c.execute(
            "SELECT id, name, category, total_calls, total_revenue_usd, total_cost_usd, "
            "(COALESCE(total_revenue_usd,0) - COALESCE(total_cost_usd,0)) as profit "
            "FROM discovered_apis WHERE total_calls > 0 ORDER BY profit DESC LIMIT 50"
        ).fetchall()
        health = c.execute(
            "SELECT COALESCE(health_status,'unknown') as status, COUNT(*) as cnt "
            "FROM discovered_apis WHERE is_active = 1 GROUP BY status"
        ).fetchall()
    return {
        "totals": {"revenue": totals[0], "cost": totals[1], "profit": totals[0] - totals[1], "calls": totals[2]},
        "top_apis": [dict(r) for r in top],
        "health": {r["status"]: r["cnt"] for r in health},
    }
