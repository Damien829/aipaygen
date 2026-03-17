"""Showcase DB — captures and serves notable API usage as social proof."""
import os
import sqlite3
import time
from datetime import datetime, timezone

DB_PATH = os.environ.get("SHOWCASE_DB", os.path.join(os.path.dirname(__file__), "showcase.db"))

# For in-memory DBs, keep a single connection alive
_memory_conn = None

# Tools considered "interesting" for showcase capture
INTERESTING_TOOLS = {"research", "code", "summarize", "translate", "chain", "sentiment", "analyze", "write"}


def _connect():
    global _memory_conn
    if DB_PATH == ":memory:":
        if _memory_conn is None:
            _memory_conn = sqlite3.connect(":memory:")
            _memory_conn.row_factory = sqlite3.Row
        return _memory_conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_showcase_db():
    """Create the showcase table if it doesn't exist."""
    with _connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS showcase (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            input_preview TEXT NOT NULL DEFAULT '',
            output_preview TEXT NOT NULL DEFAULT '',
            response_time_ms INTEGER NOT NULL DEFAULT 0,
            model TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            approved INTEGER NOT NULL DEFAULT 0
        )""")


def log_showcase(tool_name: str, input_preview: str, output_preview: str,
                 response_time_ms: int, model: str = ""):
    """Insert a showcase entry (unapproved by default)."""
    now = datetime.now(timezone.utc).isoformat()
    # Sanitize previews
    input_preview = (input_preview or "")[:100].replace("<", "&lt;").replace(">", "&gt;")
    output_preview = (output_preview or "")[:200].replace("<", "&lt;").replace(">", "&gt;")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO showcase (tool_name, input_preview, output_preview, response_time_ms, model, created_at, approved)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (tool_name, input_preview, output_preview, response_time_ms, model, now),
        )


def get_approved(limit: int = 20) -> list:
    """Return latest approved showcase entries."""
    limit = max(1, min(limit, 100))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM showcase WHERE approved = 1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending(limit: int = 50) -> list:
    """Return unapproved entries for admin review."""
    limit = max(1, min(limit, 200))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM showcase WHERE approved = 0 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def approve(entry_id: int) -> bool:
    """Approve a showcase entry."""
    with _connect() as conn:
        cur = conn.execute("UPDATE showcase SET approved = 1 WHERE id = ?", (entry_id,))
        return cur.rowcount > 0


def reject(entry_id: int) -> bool:
    """Delete a showcase entry."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM showcase WHERE id = ?", (entry_id,))
        return cur.rowcount > 0


def is_interesting(tool_name: str, response_time_ms: int) -> bool:
    """Check if a call is interesting enough to capture."""
    return tool_name in INTERESTING_TOOLS and response_time_ms < 3000


def seed_initial_data():
    """Seed 10 realistic showcase entries (approved) if table is empty."""
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM showcase").fetchone()[0]
        if count > 0:
            return False

    seeds = [
        ("research", "AI agent frameworks comparison 2026", "Compared 12 frameworks: CrewAI leads in multi-agent orchestration, AutoGen excels at code generation, LangGraph best for stateful workflows. Key trend: MCP protocol adoption up 340% YoY.", 1247, "claude-haiku"),
        ("code", "Python RSS feed parser with async", "Generated async RSS parser using aiohttp + feedparser. Includes retry logic, rate limiting, and structured output with title/link/published fields. 47 lines.", 823, "claude-haiku"),
        ("translate", "Product description EN to ES, FR, DE", "Translated product copy to 3 languages preserving marketing tone. ES: 'Potencia tu flujo de trabajo con IA...', FR: 'Boostez votre productivite avec l'IA...', DE: 'Steigern Sie Ihre Produktivitat mit KI...'", 1891, "claude-haiku"),
        ("summarize", "Technical whitepaper on zero-knowledge proofs", "ZK proofs enable verification without revealing underlying data. Key advances: STARKs eliminate trusted setup, Plonky2 achieves sub-second proving on consumer hardware. Main applications: privacy-preserving identity, scalable rollups.", 654, "claude-haiku"),
        ("analyze", "Q1 2026 SaaS churn data CSV analysis", "Churn rate: 4.2% (down from 5.8% Q4). Top churn predictors: days since last login (r=0.73), support tickets >3 (2.1x risk), plan downgrade within 30d (3.4x risk). Recommendation: trigger outreach at 14 days inactive.", 1102, "claude-haiku"),
        ("chain", "Scrape competitor pricing then compare", "3-step chain completed: (1) Scraped 8 competitor pricing pages, (2) Extracted plan tiers and features, (3) Generated comparison matrix. Found 23% price advantage on mid-tier plans.", 2340, "claude-haiku"),
        ("sentiment", "Customer review batch analysis (50 reviews)", "Overall sentiment: 78% positive, 14% neutral, 8% negative. Top positive themes: ease of use (34 mentions), fast support (21). Top negative: pricing complexity (3), API rate limits (2).", 987, "claude-haiku"),
        ("write", "Blog post about MCP protocol adoption", "Generated 1,200-word blog post covering MCP adoption trends, integration patterns, and developer experience improvements. Includes code examples for Claude Code and Cursor setup. SEO-optimized with meta description.", 1456, "claude-haiku"),
        ("research", "Best practices for LLM cost optimization", "Identified 8 strategies: prompt caching (40-60% savings), model routing by complexity, batch processing, response streaming, semantic caching, tiered model selection, token budget limits, async processing for non-urgent tasks.", 1834, "claude-haiku"),
        ("code", "TypeScript webhook handler with signature verification", "Generated Express.js webhook handler with HMAC-SHA256 signature verification, replay attack prevention (5min window), idempotency keys, and structured error responses. Includes test suite. 82 lines.", 739, "claude-haiku"),
    ]

    now = datetime.now(timezone.utc)
    with _connect() as conn:
        for i, (tool, inp, out, ms, model) in enumerate(seeds):
            # Spread timestamps over the last 24 hours
            ts = datetime.fromtimestamp(now.timestamp() - (i * 8640), tz=timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO showcase (tool_name, input_preview, output_preview, response_time_ms, model, created_at, approved)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (tool, inp, out, ms, model, ts),
            )
    return True


# Auto-init on import and seed if empty
init_showcase_db()
seed_initial_data()
