import json
import os
import threading

from flask import Blueprint, request, jsonify
from model_router import call_model
from helpers import parse_json_from_claude, require_admin, require_verified_agent

skills_bp = Blueprint("skills", __name__)

_skills_db_path = None
_skills_engine = None


def init_skills_bp(skills_db_path, skills_engine):
    global _skills_db_path, _skills_engine
    _skills_db_path = skills_db_path
    _skills_engine = skills_engine


def _init_skills_db():
    import sqlite3
    conn = sqlite3.connect(_skills_db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        source TEXT DEFAULT 'manual',
        prompt_template TEXT NOT NULL,
        model TEXT DEFAULT 'claude-haiku',
        input_schema TEXT DEFAULT '{}',
        output_hint TEXT DEFAULT '',
        calls INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    # Seed with built-in skills that map to existing endpoints
    built_in = [
        ("deep_research", "Multi-source research: web search + scrape + AI synthesis with citations", "research",
         "Research this topic deeply. Search multiple sources, synthesize findings, and provide citations.\nTopic: {{input}}\n\nReturn JSON: {\"summary\": \"...\", \"key_points\": [...], \"sources\": [...], \"confidence\": 0.0-1.0}",
         "claude-haiku", '{"input": "topic to research"}'),
        ("market_analysis", "Analyze a market, competitors, trends, and opportunities", "business",
         "Analyze this market. Cover: market size, key players, trends, opportunities, threats.\nMarket: {{input}}\n\nReturn JSON: {\"market_size\": \"...\", \"key_players\": [...], \"trends\": [...], \"opportunities\": [...], \"threats\": [...]}",
         "claude-haiku", '{"input": "market or industry to analyze"}'),
        ("code_review", "Review code for bugs, security issues, and improvements", "engineering",
         "Review this code. Find: bugs, security vulnerabilities, performance issues, style problems.\nCode:\n{{input}}\n\nReturn JSON: {\"issues\": [{\"severity\": \"high|medium|low\", \"type\": \"bug|security|perf|style\", \"line\": \"...\", \"description\": \"...\", \"fix\": \"...\"}], \"score\": 0-10, \"summary\": \"...\"}",
         "claude-haiku", '{"input": "code to review"}'),
        ("data_pipeline", "Build a data transformation pipeline from description", "engineering",
         "Design a data pipeline. Input: {{input}}\n\nReturn JSON: {\"steps\": [{\"name\": \"...\", \"operation\": \"...\", \"input\": \"...\", \"output\": \"...\"}], \"code\": \"python code\", \"diagram\": \"mermaid\"}",
         "claude-haiku", '{"input": "pipeline description"}'),
        ("legal_summary", "Summarize legal documents, contracts, or terms of service", "legal",
         "Summarize this legal document. Highlight: key obligations, rights, risks, deadlines.\nDocument:\n{{input}}\n\nReturn JSON: {\"summary\": \"...\", \"key_obligations\": [...], \"risks\": [...], \"deadlines\": [...], \"recommendation\": \"...\"}",
         "claude-haiku", '{"input": "legal text to analyze"}'),
        ("financial_analysis", "Analyze financial data, reports, or investment opportunities", "finance",
         "Analyze this financial information. Cover: revenue, profitability, growth, risks, valuation.\nData:\n{{input}}\n\nReturn JSON: {\"summary\": \"...\", \"metrics\": {...}, \"strengths\": [...], \"risks\": [...], \"outlook\": \"...\"}",
         "claude-haiku", '{"input": "financial data or report"}'),
        ("content_strategy", "Create a content strategy for a brand, product, or topic", "marketing",
         "Create a content strategy. Consider: audience, channels, content types, frequency, KPIs.\nBrief:\n{{input}}\n\nReturn JSON: {\"audience\": {...}, \"channels\": [...], \"content_calendar\": [...], \"kpis\": [...], \"budget_estimate\": \"...\"}",
         "claude-haiku", '{"input": "brand/product/topic brief"}'),
        ("api_design", "Design a REST API from requirements", "engineering",
         "Design a REST API. Include: endpoints, methods, request/response schemas, auth.\nRequirements:\n{{input}}\n\nReturn JSON: {\"base_url\": \"...\", \"auth\": \"...\", \"endpoints\": [{\"method\": \"...\", \"path\": \"...\", \"description\": \"...\", \"request\": {...}, \"response\": {...}}]}",
         "claude-haiku", '{"input": "API requirements"}'),
        ("competitor_intel", "Gather competitive intelligence on a company or product", "business",
         "Analyze this competitor. Cover: products, pricing, strengths, weaknesses, market position.\nCompetitor:\n{{input}}\n\nReturn JSON: {\"company\": \"...\", \"products\": [...], \"pricing\": \"...\", \"strengths\": [...], \"weaknesses\": [...], \"market_share\": \"...\", \"strategy\": \"...\"}",
         "claude-haiku", '{"input": "company or product name"}'),
        ("teach_concept", "Explain any concept with examples, analogies, and exercises", "education",
         "Teach this concept. Use: clear explanation, real-world analogy, 3 examples, 2 practice exercises.\nConcept:\n{{input}}\n\nReturn JSON: {\"explanation\": \"...\", \"analogy\": \"...\", \"examples\": [...], \"exercises\": [...], \"common_mistakes\": [...], \"difficulty\": \"beginner|intermediate|advanced\"}",
         "claude-haiku", '{"input": "concept to teach"}'),
    ]
    for name, desc, cat, template, model, schema in built_in:
        conn.execute(
            "INSERT OR IGNORE INTO skills (name, description, category, source, prompt_template, model, input_schema) VALUES (?, ?, ?, 'built-in', ?, ?, ?)",
            (name, desc, cat, template, model, schema),
        )
    conn.commit()
    conn.close()


@skills_bp.route("/skills", methods=["GET"])
def list_skills():
    """List all available skills — agents discover what we can do."""
    import sqlite3
    category = request.args.get("category")
    conn = sqlite3.connect(_skills_db_path)
    conn.row_factory = sqlite3.Row
    if category:
        rows = conn.execute("SELECT id, name, description, category, source, input_schema, calls FROM skills WHERE category = ? ORDER BY calls DESC", (category,)).fetchall()
    else:
        rows = conn.execute("SELECT id, name, description, category, source, input_schema, calls FROM skills ORDER BY calls DESC").fetchall()
    conn.close()
    skills = [dict(r) for r in rows]
    categories = list(set(s["category"] for s in skills))
    return jsonify({"skills": skills, "total": len(skills), "categories": categories})


@skills_bp.route("/skills/execute", methods=["POST"])
@require_admin
def execute_skill():
    """Execute any skill by name with input. The universal agent endpoint."""
    import sqlite3
    data = request.get_json(force=True) or {}
    skill_name = data.get("skill") or data.get("name")
    skill_input = data.get("input", "")
    model = data.get("model", None)

    if not skill_name:
        return jsonify({"error": "skill name required"}), 400

    conn = sqlite3.connect(_skills_db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM skills WHERE name = ?", (skill_name,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": f"skill '{skill_name}' not found", "hint": "GET /skills to see available skills"}), 404

    skill = dict(row)
    use_model = model or skill["model"]
    prompt = skill["prompt_template"].replace("{{input}}", str(skill_input))

    result = call_model(use_model, [{"role": "user", "content": prompt}],
        system="You are an expert assistant. Always respond with valid JSON only — no markdown, no preamble.",
        max_tokens=2048)

    conn.execute("UPDATE skills SET calls = calls + 1, updated_at = CURRENT_TIMESTAMP WHERE name = ?", (skill_name,))
    conn.commit()
    conn.close()

    parsed = parse_json_from_claude(result["text"])
    return jsonify({
        "skill": skill_name,
        "model": result["model"],
        "result": parsed if parsed else result["text"],
        "cost_usd": result.get("cost_usd", 0),
    })


@skills_bp.route("/skills/create", methods=["POST"])
@require_verified_agent
def create_skill():
    """Let verified agents create new skills dynamically. Requires JWT auth."""
    import sqlite3
    data = request.get_json(force=True) or {}
    name = data.get("name")
    description = data.get("description")
    prompt_template = data.get("prompt_template")
    category = data.get("category", "general")
    model = data.get("model", "claude-haiku")
    input_schema = json.dumps(data.get("input_schema", {"input": "string"}))

    if not all([name, description, prompt_template]):
        return jsonify({"error": "name, description, and prompt_template required"}), 400

    if "{{input}}" not in prompt_template:
        return jsonify({"error": "prompt_template must contain {{input}} placeholder"}), 400

    conn = sqlite3.connect(_skills_db_path)
    try:
        conn.execute(
            "INSERT INTO skills (name, description, category, source, prompt_template, model, input_schema) VALUES (?, ?, ?, 'agent-created', ?, ?, ?)",
            (name, description, category, prompt_template, model, input_schema),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": f"skill '{name}' already exists"}), 409
    conn.close()
    return jsonify({"created": name, "description": description, "category": category})


@skills_bp.route("/skills/absorb", methods=["POST"])
@require_admin
def absorb_skill():
    """Absorb a skill from an external source — URL, API spec, or description.
    AiPayGen reads the source and creates a callable skill automatically."""
    import sqlite3
    data = request.get_json(force=True) or {}
    source_url = data.get("url", "")
    source_text = data.get("text", "")
    category = data.get("category", "general")

    if not source_url and not source_text:
        return jsonify({"error": "provide url or text to absorb a skill from"}), 400

    # If URL provided, fetch it (with SSRF protection)
    content = source_text
    if source_url:
        from security import safe_fetch
        resp = safe_fetch(source_url, user_agent="AiPayGen-SkillAbsorber/1.0", timeout=30, max_size=10000)
        if resp.get("blocked"):
            return jsonify({"error": resp["error"]}), 403
        if "error" in resp:
            return jsonify({"error": f"failed to fetch URL: {resp['error']}"}), 400
        content = resp.get("body", "")

    # Use AI to extract a skill definition from the content
    result = call_model("claude-haiku", [{"role": "user", "content": f"""Analyze this content and create a reusable AI skill from it.

Content:
{content[:8000]}

Return JSON with:
- "name": snake_case skill name (unique, descriptive)
- "description": one-line description of what this skill does
- "category": one of: research, engineering, business, finance, marketing, legal, education, data, creative, general
- "prompt_template": a prompt template that uses {{{{input}}}} placeholder for the user's input. The template should produce structured JSON output.
- "input_schema": {{"input": "description of expected input"}}
"""}],
        system="You are a skill extraction expert. Always respond with valid JSON only.", max_tokens=1024)

    parsed = parse_json_from_claude(result["text"])
    if not parsed or "name" not in parsed:
        return jsonify({"error": "could not extract skill from content", "raw": result["text"]}), 422

    conn = sqlite3.connect(_skills_db_path)
    try:
        conn.execute(
            "INSERT INTO skills (name, description, category, source, prompt_template, model, input_schema) VALUES (?, ?, ?, ?, ?, 'claude-haiku', ?)",
            (parsed["name"], parsed["description"], parsed.get("category", category),
             source_url or "text-input", parsed["prompt_template"],
             json.dumps(parsed.get("input_schema", {"input": "string"}))),
        )
        conn.commit()
        conn.close()
        _skills_engine.invalidate()
        return jsonify({"absorbed": parsed["name"], "description": parsed["description"],
                        "category": parsed.get("category", category), "source": source_url or "text"})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": f"skill '{parsed['name']}' already exists", "skill": parsed}), 409


@skills_bp.route("/skills/harvest", methods=["POST"])
@require_admin
def trigger_harvest():
    """Trigger skill harvesting from external sources on demand."""
    source = (request.get_json(force=True) or {}).get("source", "all")
    from skill_harvester import SkillHarvester
    h = SkillHarvester(call_model, parse_json_from_claude)
    if source == "all":
        threading.Thread(target=h.run_all, daemon=True).start()
    elif source == "mcp":
        threading.Thread(target=h.harvest_mcp_registries, daemon=True).start()
    elif source == "github":
        threading.Thread(target=h.harvest_awesome_lists, daemon=True).start()
    elif source == "api":
        threading.Thread(target=h.harvest_api_directories, daemon=True).start()
    else:
        return jsonify({"error": "source must be: all, mcp, github, or api"}), 400
    return jsonify({"status": "harvest started", "source": source})


@skills_bp.route("/skills/harvest/stats", methods=["GET"])
@require_admin
def harvest_stats():
    """Get skill harvest statistics."""
    from skill_harvester import SkillHarvester
    h = SkillHarvester(call_model, parse_json_from_claude)
    return jsonify(h.get_stats())


_outbound_lock = threading.Lock()


@skills_bp.route("/outbound/run", methods=["POST"])
@require_admin
def trigger_outbound():
    """Trigger outbound recruitment agent manually."""
    if not _outbound_lock.acquire(blocking=False):
        return jsonify({"status": "already running"}), 409
    def _run():
        try:
            from outbound_agent import OutboundAgent
            OutboundAgent(call_model, parse_json_from_claude).run_all()
        finally:
            _outbound_lock.release()
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "outbound run started"})


@skills_bp.route("/outbound/stats", methods=["GET"])
@require_admin
def outbound_stats():
    """Get outbound recruitment agent statistics."""
    from outbound_agent import OutboundAgent
    agent = OutboundAgent(call_model, parse_json_from_claude)
    return jsonify(agent.get_stats())


@skills_bp.route("/skills/search", methods=["GET"])
@require_admin
def search_skills():
    """Search skills by keyword — TF-IDF ranked relevance search."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    top_n = request.args.get("top_n", 20, type=int)
    _STRIP_FIELDS = {"source", "source_url", "harvested_from", "origin", "crawled_from"}
    results = [
        {k: v for k, v in r.items() if k not in _STRIP_FIELDS}
        for r in _skills_engine.search(q, top_n=min(top_n, 50))
    ]
    return jsonify({"query": q, "results": results})


@skills_bp.route("/ask", methods=["POST"])
def ask_universal():
    """Universal agent endpoint — describe what you need, AiPayGen picks the best skill and model."""
    import sqlite3
    data = request.get_json(force=True) or {}
    question = data.get("question") or data.get("input") or data.get("query", "")
    if not question:
        return jsonify({"error": "question/input/query required"}), 400

    # First, find candidate skills via TF-IDF
    candidates = _skills_engine.search(question, top_n=30)
    if not candidates:
        import sqlite3 as _sq
        _conn = _sq.connect(_skills_db_path)
        _conn.row_factory = _sq.Row
        candidates = [dict(r) for r in _conn.execute("SELECT name, description, category FROM skills ORDER BY calls DESC LIMIT 30").fetchall()]
        _conn.close()

    skill_list = "\n".join(f"- {s['name']}: {s['description']}" for s in candidates)

    # Use AI to pick the best skill
    router_result = call_model("claude-haiku", [{"role": "user", "content": f"""Given this user request, pick the best skill to handle it. If no skill fits well, respond with "direct".

User request: {question}

Available skills:
{skill_list}

Return JSON: {{"skill": "skill_name_or_direct", "reasoning": "why this skill"}}"""}],
        system="You are a routing assistant. Always respond with valid JSON only.", max_tokens=256)

    routed = parse_json_from_claude(router_result["text"])
    chosen_skill = routed.get("skill", "direct") if routed else "direct"

    if chosen_skill != "direct":
        # Execute the matched skill
        conn = sqlite3.connect(_skills_db_path)
        conn.row_factory = sqlite3.Row
        skill_row = conn.execute("SELECT * FROM skills WHERE name = ?", (chosen_skill,)).fetchone()
        if skill_row:
            skill = dict(skill_row)
            prompt = skill["prompt_template"].replace("{{input}}", question)
            result = call_model(skill["model"], [{"role": "user", "content": prompt}],
                system="You are an expert assistant. Always respond with valid JSON only.", max_tokens=2048)
            conn.execute("UPDATE skills SET calls = calls + 1, updated_at = CURRENT_TIMESTAMP WHERE name = ?", (chosen_skill,))
            conn.commit()
            conn.close()
            parsed = parse_json_from_claude(result["text"])
            return jsonify({
                "skill_used": chosen_skill,
                "routing_reason": routed.get("reasoning", ""),
                "model": result["model"],
                "result": parsed if parsed else result["text"],
                "cost_usd": result.get("cost_usd", 0),
            })
        conn.close()

    # Direct answer — no skill matched
    result = call_model("claude-haiku", [{"role": "user", "content": question}],
        system="You are a helpful assistant. Provide clear, structured answers.", max_tokens=2048)
    return jsonify({
        "skill_used": "direct",
        "model": result["model"],
        "result": result["text"],
        "cost_usd": result.get("cost_usd", 0),
    })
