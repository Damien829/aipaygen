"""Blueprint for the Build Your Own AI Agent feature."""

import json
import os
import sqlite3
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, render_template_string

from model_router import call_model
from helpers import log_payment, agent_response
from agent_memory import memory_search, memory_set

builder_bp = Blueprint("builder", __name__)

# Set via init_builder_bp()
_BATCH_HANDLERS = None
_skills_db_path = None
_skills_engine = None

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_builder.db")


def init_builder_bp(skills_db_path, skills_engine, batch_handlers):
    global _BATCH_HANDLERS, _skills_db_path, _skills_engine
    _BATCH_HANDLERS = batch_handlers
    _skills_db_path = skills_db_path
    _skills_engine = skills_engine


# ─── Database ──────────────────────────────────────────────────────────────────

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_builder_db():
    """Create tables if they don't exist and seed default templates."""
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents_custom (
            id TEXT PRIMARY KEY,
            creator_key TEXT,
            name TEXT NOT NULL,
            avatar_url TEXT,
            system_prompt TEXT NOT NULL,
            tools TEXT,
            model TEXT DEFAULT 'auto',
            memory_enabled INTEGER DEFAULT 1,
            knowledge_base TEXT,
            template_id TEXT,
            schedule TEXT,
            price_per_use REAL,
            marketplace INTEGER DEFAULT 0,
            is_public INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar_url TEXT,
            system_prompt TEXT NOT NULL,
            tools TEXT,
            model TEXT DEFAULT 'auto',
            memory_enabled INTEGER DEFAULT 1,
            knowledge_base TEXT,
            template_id TEXT,
            schedule TEXT,
            price_per_use REAL,
            marketplace INTEGER DEFAULT 0,
            is_public INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            category TEXT,
            description TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            agent_id TEXT,
            task TEXT,
            result TEXT,
            status TEXT,
            triggered_by TEXT,
            created_at TEXT,
            completed_at TEXT
        )
    """)
    conn.commit()

    # Seed default templates if empty
    count = conn.execute("SELECT COUNT(*) FROM agent_templates").fetchone()[0]
    if count == 0:
        _seed_templates(conn)
    conn.close()


def _seed_templates(conn):
    now = datetime.utcnow().isoformat() + "Z"
    templates = [
        {
            "id": str(uuid.uuid4()),
            "name": "Research Agent",
            "system_prompt": "You are a thorough research agent. Given a topic or question, search the web, gather information from multiple sources, and produce a well-structured summary with citations.",
            "tools": json.dumps(["research", "summarize", "web_search", "scrape_website"]),
            "model": "auto",
            "category": "research",
            "description": "Searches the web and synthesizes findings into structured reports.",
            "schedule": None,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Crypto Tracker",
            "system_prompt": "You are a crypto market analyst agent. Monitor cryptocurrency prices, analyze trends, and store insights in memory for longitudinal tracking.",
            "tools": json.dumps(["get_crypto_prices", "analyze", "memory_store"]),
            "model": "auto",
            "category": "finance",
            "description": "Tracks crypto prices and analyzes market trends on a schedule.",
            "schedule": json.dumps({"type": "loop", "config": {"minutes": 30}}),
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Content Writer",
            "system_prompt": "You are a professional content writer. Create, rewrite, and polish written content for blogs, social media, and marketing. Always proofread your output.",
            "tools": json.dumps(["write", "rewrite", "proofread", "social", "headline"]),
            "model": "auto",
            "category": "content",
            "description": "Creates and polishes blog posts, social media content, and marketing copy.",
            "schedule": None,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Customer Support",
            "system_prompt": "You are a customer support agent. Answer questions accurately using the provided context, detect sentiment to escalate unhappy customers, classify issues by type, and remember past interactions.",
            "tools": json.dumps(["qa", "sentiment", "classify", "memory_store"]),
            "model": "auto",
            "category": "support",
            "description": "Handles customer questions with sentiment detection and issue classification.",
            "schedule": None,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Social Media Manager",
            "system_prompt": "You are a social media manager agent. Create engaging posts, craft headlines, and monitor social platforms for trends and engagement opportunities.",
            "tools": json.dumps(["social", "headline", "scrape_tweets", "scrape_instagram"]),
            "model": "auto",
            "category": "marketing",
            "description": "Creates social posts and monitors platforms daily.",
            "schedule": json.dumps({"type": "cron", "config": {"hour": 9, "minute": 0}}),
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Code Helper",
            "system_prompt": "You are an expert programming assistant. Write clean code, explain complex concepts clearly, and generate comprehensive test cases.",
            "tools": json.dumps(["code", "explain", "test_cases"]),
            "model": "auto",
            "category": "development",
            "description": "Writes code, explains concepts, and generates test cases.",
            "schedule": None,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Data Analyst",
            "system_prompt": "You are a data analyst agent. Analyze datasets, extract insights, compare metrics, generate diagrams, and write SQL queries to answer data questions.",
            "tools": json.dumps(["analyze", "extract", "compare", "diagram", "sql"]),
            "model": "auto",
            "category": "analytics",
            "description": "Analyzes data, generates charts, and writes SQL queries.",
            "schedule": None,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "News Monitor",
            "system_prompt": "You are a news monitoring agent. Continuously search for breaking news, summarize articles, extract keywords, and produce research briefs on developing stories.",
            "tools": json.dumps(["web_search", "summarize", "keywords", "research"]),
            "model": "auto",
            "category": "research",
            "description": "Monitors the web for news and produces hourly briefings.",
            "schedule": json.dumps({"type": "loop", "config": {"hours": 1}}),
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Personal Assistant",
            "system_prompt": "You are a personal assistant agent. Help with planning, decision-making, email drafting, and remembering important information across conversations.",
            "tools": json.dumps(["ask", "plan", "decide", "memory_store", "email"]),
            "model": "auto",
            "category": "productivity",
            "description": "Plans, decides, drafts emails, and remembers context across sessions.",
            "schedule": None,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Sales Bot",
            "system_prompt": "You are an AI sales agent. Research prospects, enrich lead data, craft personalized pitches, score leads, and draft outreach emails.",
            "tools": json.dumps(["pitch", "enrich_entity", "email", "score", "classify"]),
            "model": "auto",
            "category": "sales",
            "description": "Researches prospects, scores leads, and crafts personalized outreach.",
            "schedule": None,
        },
    ]
    for t in templates:
        conn.execute("""
            INSERT INTO agent_templates
                (id, name, system_prompt, tools, model, category, description, schedule,
                 memory_enabled, is_public, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 'active', ?, ?)
        """, (t["id"], t["name"], t["system_prompt"], t["tools"], t["model"],
              t["category"], t["description"], t["schedule"], now, now))
    conn.commit()


# ─── Auth helper ───────────────────────────────────────────────────────────────

def _get_api_key():
    """Extract API key from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return auth.strip() or None


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for field in ("tools", "knowledge_base", "schedule"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ─── Scheduling helpers ───────────────────────────────────────────────────────

def _schedule_agent_job(agent_id, schedule_config):
    """Register an APScheduler job for a custom agent."""
    from scheduler import get_scheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    scheduler = get_scheduler()
    job_id = f"agent_custom_{agent_id}"

    # Remove existing job if any
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    stype = schedule_config.get("type")
    config = schedule_config.get("config", {})

    if stype == "loop":
        trigger = IntervalTrigger(
            minutes=config.get("minutes", 0),
            hours=config.get("hours", 0),
        )
    elif stype == "cron":
        trigger = CronTrigger(
            minute=config.get("minute", 0),
            hour=config.get("hour", "*"),
            day=config.get("day", "*"),
            day_of_week=config.get("day_of_week", "*"),
            month=config.get("month", "*"),
        )
    elif stype == "event":
        # Events are handled externally; just store config, no scheduler job
        return
    else:
        return

    scheduler.add_job(_run_scheduled_agent, trigger, id=job_id, args=[agent_id],
                      replace_existing=True, misfire_grace_time=300)


def _remove_agent_job(agent_id):
    """Remove an APScheduler job for a custom agent."""
    from scheduler import get_scheduler
    try:
        get_scheduler().remove_job(f"agent_custom_{agent_id}")
    except Exception:
        pass


def _run_scheduled_agent(agent_id):
    """Execute a custom agent on schedule (called by APScheduler)."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM agents_custom WHERE id = ? AND status = 'active'",
                       (agent_id,)).fetchone()
    conn.close()
    if not row:
        return
    agent = _row_to_dict(row)
    schedule = agent.get("schedule", {})
    task = "Run your scheduled task based on your system prompt."
    if isinstance(schedule, dict):
        task = schedule.get("config", {}).get("task", task)
    _execute_agent_run(agent, task, triggered_by="loop" if (isinstance(schedule, dict) and schedule.get("type") == "loop") else "cron")


def _execute_agent_run(agent_config, task, triggered_by="manual"):
    """Core execution: run a custom agent and record the result."""
    from react_agent import ReActAgent, make_tool_handler

    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat() + "Z"
    agent_id = agent_config["id"]

    # Record run as started
    conn = _get_db()
    conn.execute("""
        INSERT INTO agent_runs (id, agent_id, task, status, triggered_by, created_at)
        VALUES (?, ?, ?, 'running', ?, ?)
    """, (run_id, agent_id, task, triggered_by, now))
    conn.commit()
    conn.close()

    try:
        memory_fns = {}
        if agent_config.get("memory_enabled"):
            memory_fns = {"search": memory_search, "set": memory_set}

        tool_handler = make_tool_handler(
            batch_handlers=_BATCH_HANDLERS,
            memory_search_fn=memory_search if agent_config.get("memory_enabled") else None,
            memory_set_fn=memory_set if agent_config.get("memory_enabled") else None,
            skills_db_path=_skills_db_path,
            agent_id=agent_id,
            skills_search_engine=_skills_engine,
            call_model_fn=call_model,
        )

        # Build system prompt
        system_prompt = agent_config.get("system_prompt", "")
        enabled_tools = agent_config.get("tools", [])
        if isinstance(enabled_tools, str):
            try:
                enabled_tools = json.loads(enabled_tools)
            except (json.JSONDecodeError, TypeError):
                enabled_tools = []

        model = agent_config.get("model", "auto")

        agent = ReActAgent(
            call_model_fn=call_model,
            tool_handler_fn=tool_handler,
            memory_fns=memory_fns,
            system_prompt=system_prompt,
        )

        result = agent.run(
            task=task,
            max_steps=10,
            max_cost_usd=1.0,
            model=model,
            agent_id=agent_id,
            allowed_tools=enabled_tools if enabled_tools else None,
        )

        result_json = json.dumps(result)
        completed_at = datetime.utcnow().isoformat() + "Z"

        conn = _get_db()
        conn.execute("""
            UPDATE agent_runs SET result = ?, status = 'completed', completed_at = ?
            WHERE id = ?
        """, (result_json, completed_at, run_id))
        conn.commit()
        conn.close()

        return {"run_id": run_id, "status": "completed", "result": result}

    except Exception as e:
        completed_at = datetime.utcnow().isoformat() + "Z"
        conn = _get_db()
        conn.execute("""
            UPDATE agent_runs SET result = ?, status = 'failed', completed_at = ?
            WHERE id = ?
        """, (json.dumps({"error": str(e)}), completed_at, run_id))
        conn.commit()
        conn.close()
        return {"run_id": run_id, "status": "failed", "error": str(e)}


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@builder_bp.route("/agents/build", methods=["POST"])
def create_agent():
    """Create a custom AI agent."""
    data = request.get_json() or {}
    api_key = _get_api_key()

    name = data.get("name", "").strip()
    system_prompt = data.get("system_prompt", "").strip()
    if not name or not system_prompt:
        return jsonify({"error": "name and system_prompt are required"}), 400

    if len(name) > 100:
        return jsonify({"error": "name must be 100 characters or less"}), 400
    if len(system_prompt) > 5000:
        return jsonify({"error": "system_prompt must be 5000 characters or less"}), 400

    tools = data.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 106:
        return jsonify({"error": "tools must be a list of up to 106 tool names"}), 400

    # Validate tool names are alphanumeric/underscore only
    import re
    for t in tools:
        if not isinstance(t, str) or not re.match(r'^[a-z_]{1,50}$', t):
            return jsonify({"error": f"invalid tool name: {t}"}), 400

    agent_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat() + "Z"
    knowledge_base = data.get("knowledge_base", [])
    schedule = data.get("schedule")

    conn = _get_db()
    conn.execute("""
        INSERT INTO agents_custom
            (id, creator_key, name, avatar_url, system_prompt, tools, model,
             memory_enabled, knowledge_base, template_id, schedule, price_per_use,
             marketplace, is_public, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
    """, (
        agent_id,
        api_key,
        name,
        data.get("avatar_url"),
        system_prompt,
        json.dumps(tools) if isinstance(tools, list) else tools,
        data.get("model", "auto"),
        1 if data.get("memory_enabled", True) else 0,
        json.dumps(knowledge_base) if isinstance(knowledge_base, list) else knowledge_base,
        data.get("template_id"),
        json.dumps(schedule) if schedule else None,
        data.get("price_per_use"),
        1 if data.get("marketplace") else 0,
        1 if data.get("is_public") else 0,
        now, now,
    ))
    conn.commit()
    conn.close()

    # Register schedule if provided
    if schedule and isinstance(schedule, dict):
        try:
            _schedule_agent_job(agent_id, schedule)
        except Exception:
            pass

    log_payment("/agents/build", 0.05, request.remote_addr)
    return jsonify(agent_response({
        "agent_id": agent_id,
        "name": name,
        "status": "active",
        "config": {
            "system_prompt": system_prompt,
            "tools": tools,
            "model": data.get("model", "auto"),
            "memory_enabled": data.get("memory_enabled", True),
            "schedule": schedule,
        },
        "created_at": now,
    }, "/agents/build")), 201


@builder_bp.route("/agents/custom", methods=["GET"])
def list_custom_agents():
    """List the caller's custom agents."""
    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "Authorization header required"}), 401

    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM agents_custom WHERE creator_key = ? AND status != 'archived' ORDER BY created_at DESC",
        (api_key,)
    ).fetchall()
    conn.close()

    agents = [_row_to_dict(r) for r in rows]
    return jsonify(agent_response({"agents": agents, "count": len(agents)}, "/agents/custom"))


@builder_bp.route("/agents/custom/<agent_id>", methods=["GET"])
def get_custom_agent(agent_id):
    """Get details of a custom agent."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM agents_custom WHERE id = ?", (agent_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "agent not found"}), 404

    agent = _row_to_dict(row)
    api_key = _get_api_key()
    if agent["status"] == "archived":
        return jsonify({"error": "agent not found"}), 404
    if not agent.get("is_public") and agent.get("creator_key") != api_key:
        return jsonify({"error": "unauthorized"}), 403

    return jsonify(agent_response(agent, f"/agents/custom/{agent_id}"))


@builder_bp.route("/agents/custom/<agent_id>", methods=["PUT"])
def update_custom_agent(agent_id):
    """Update a custom agent's configuration."""
    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "Authorization header required"}), 401

    conn = _get_db()
    row = conn.execute("SELECT * FROM agents_custom WHERE id = ? AND creator_key = ?",
                       (agent_id, api_key)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "agent not found or unauthorized"}), 404

    data = request.get_json() or {}

    if "name" in data:
        n = data["name"] if isinstance(data["name"], str) else ""
        if len(n.strip()) == 0:
            conn.close()
            return jsonify({"error": "name cannot be empty"}), 400
        if len(n) > 100:
            conn.close()
            return jsonify({"error": "name must be 100 characters or less"}), 400
    if "system_prompt" in data:
        sp = data["system_prompt"] if isinstance(data["system_prompt"], str) else ""
        if len(sp.strip()) == 0:
            conn.close()
            return jsonify({"error": "system_prompt cannot be empty"}), 400
        if len(sp) > 5000:
            conn.close()
            return jsonify({"error": "system_prompt must be 5000 characters or less"}), 400

    now = datetime.utcnow().isoformat() + "Z"

    updatable = ["name", "avatar_url", "system_prompt", "tools", "model",
                 "memory_enabled", "knowledge_base", "schedule", "price_per_use",
                 "marketplace", "is_public"]

    sets = ["updated_at = ?"]
    vals = [now]

    for field in updatable:
        if field in data:
            val = data[field]
            if field in ("tools", "knowledge_base", "schedule"):
                val = json.dumps(val) if val is not None else None
            elif field in ("memory_enabled", "marketplace", "is_public"):
                val = 1 if val else 0
            sets.append(f"{field} = ?")
            vals.append(val)

    vals.append(agent_id)
    conn.execute(f"UPDATE agents_custom SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()

    # Update schedule job if schedule changed
    if "schedule" in data:
        _remove_agent_job(agent_id)
        if data["schedule"] and isinstance(data["schedule"], dict):
            try:
                _schedule_agent_job(agent_id, data["schedule"])
            except Exception:
                pass

    row = conn.execute("SELECT * FROM agents_custom WHERE id = ?", (agent_id,)).fetchone()
    conn.close()

    log_payment(f"/agents/custom/{agent_id}", 0.01, request.remote_addr)
    return jsonify(agent_response(_row_to_dict(row), f"/agents/custom/{agent_id}"))


@builder_bp.route("/agents/custom/<agent_id>", methods=["DELETE"])
def delete_custom_agent(agent_id):
    """Archive a custom agent."""
    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "Authorization header required"}), 401

    conn = _get_db()
    row = conn.execute("SELECT * FROM agents_custom WHERE id = ? AND creator_key = ?",
                       (agent_id, api_key)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "agent not found or unauthorized"}), 404

    now = datetime.utcnow().isoformat() + "Z"
    conn.execute("UPDATE agents_custom SET status = 'archived', updated_at = ? WHERE id = ?",
                 (now, agent_id))
    conn.commit()
    conn.close()

    _remove_agent_job(agent_id)

    return jsonify(agent_response({"agent_id": agent_id, "status": "archived"}, f"/agents/custom/{agent_id}"))


@builder_bp.route("/agents/custom/<agent_id>/run", methods=["POST"])
def run_custom_agent(agent_id):
    """Run a custom agent with a task."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM agents_custom WHERE id = ? AND status = 'active'",
                       (agent_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "agent not found or inactive"}), 404

    agent_config = _row_to_dict(row)
    api_key = _get_api_key()
    if not agent_config.get("is_public") and agent_config.get("creator_key") != api_key:
        return jsonify({"error": "unauthorized"}), 403

    data = request.get_json() or {}
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "task is required"}), 400

    result = _execute_agent_run(agent_config, task, triggered_by="manual")

    cost = 0.10
    if result.get("result") and isinstance(result["result"], dict):
        cost = result["result"].get("total_cost_usd", 0.10)
    log_payment(f"/agents/custom/{agent_id}/run", cost, request.remote_addr)

    return jsonify(agent_response(result, f"/agents/custom/{agent_id}/run"))


@builder_bp.route("/agents/custom/<agent_id>/schedule", methods=["POST"])
def set_agent_schedule(agent_id):
    """Set or update agent schedule."""
    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "Authorization header required"}), 401

    conn = _get_db()
    row = conn.execute("SELECT * FROM agents_custom WHERE id = ? AND creator_key = ?",
                       (agent_id, api_key)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "agent not found or unauthorized"}), 404

    data = request.get_json() or {}
    stype = data.get("type")
    if stype not in ("loop", "cron", "event"):
        conn.close()
        return jsonify({"error": "type must be loop, cron, or event"}), 400

    config = data.get("config", {})

    if stype == "loop":
        total_minutes = config.get("minutes", 0) + config.get("hours", 0) * 60
        if total_minutes <= 0 or total_minutes > 1440:
            conn.close()
            return jsonify({"error": "loop interval must be between 1 and 1440 minutes"}), 400

    if stype == "cron":
        hour = config.get("hour", "*")
        if hour != "*":
            if not isinstance(hour, int) or hour < 0 or hour > 23:
                conn.close()
                return jsonify({"error": "cron hour must be 0-23 or '*'"}), 400

    schedule = {"type": stype, "config": config}
    now = datetime.utcnow().isoformat() + "Z"

    conn.execute("UPDATE agents_custom SET schedule = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(schedule), now, agent_id))
    conn.commit()
    conn.close()

    _remove_agent_job(agent_id)
    try:
        _schedule_agent_job(agent_id, schedule)
    except Exception:
        pass

    log_payment(f"/agents/custom/{agent_id}/schedule", 0.01, request.remote_addr)
    return jsonify(agent_response({"agent_id": agent_id, "schedule": schedule}, f"/agents/custom/{agent_id}/schedule"))


@builder_bp.route("/agents/custom/<agent_id>/schedule", methods=["DELETE"])
def remove_agent_schedule(agent_id):
    """Remove agent schedule."""
    api_key = _get_api_key()
    if not api_key:
        return jsonify({"error": "Authorization header required"}), 401

    conn = _get_db()
    row = conn.execute("SELECT * FROM agents_custom WHERE id = ? AND creator_key = ?",
                       (agent_id, api_key)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "agent not found or unauthorized"}), 404

    now = datetime.utcnow().isoformat() + "Z"
    conn.execute("UPDATE agents_custom SET schedule = NULL, updated_at = ? WHERE id = ?",
                 (now, agent_id))
    conn.commit()
    conn.close()

    _remove_agent_job(agent_id)

    return jsonify(agent_response({"agent_id": agent_id, "schedule": None}, f"/agents/custom/{agent_id}/schedule"))


@builder_bp.route("/agents/custom/<agent_id>/runs", methods=["GET"])
def list_agent_runs(agent_id):
    """Get execution history for a custom agent."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM agents_custom WHERE id = ?", (agent_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "agent not found"}), 404

    agent = _row_to_dict(row)
    api_key = _get_api_key()
    if not agent.get("is_public") and agent.get("creator_key") != api_key:
        conn.close()
        return jsonify({"error": "unauthorized"}), 403

    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    rows = conn.execute(
        "SELECT * FROM agent_runs WHERE agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (agent_id, limit, offset)
    ).fetchall()
    conn.close()

    runs = []
    for r in rows:
        d = dict(r)
        if d.get("result"):
            try:
                d["result"] = json.loads(d["result"])
            except (json.JSONDecodeError, TypeError):
                pass
        runs.append(d)

    return jsonify(agent_response({"agent_id": agent_id, "runs": runs, "count": len(runs)}, f"/agents/custom/{agent_id}/runs"))


@builder_bp.route("/builder/templates", methods=["GET"])
def list_templates():
    """List all agent templates."""
    conn = _get_db()
    rows = conn.execute("SELECT * FROM agent_templates WHERE status = 'active' ORDER BY name").fetchall()
    conn.close()

    templates = [_row_to_dict(r) for r in rows]
    return jsonify(agent_response({"templates": templates, "count": len(templates)}, "/builder/templates"))


@builder_bp.route("/builder", methods=["GET"])
def builder_page():
    """Visual agent builder page."""
    from routes.meta import NAV_HTML, FOOTER_HTML
    template_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "builder.html")
    with open(template_path, "r") as f:
        html = f.read()
    return render_template_string(html, nav=NAV_HTML, footer=FOOTER_HTML)
