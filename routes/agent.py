"""Blueprint for autonomous agent endpoint, agent identity, memory, registry, and chain."""

import json
import re as _re
from datetime import datetime

from flask import Blueprint, request, jsonify, Response
from model_router import call_model
from helpers import log_payment, agent_response, get_client_ip as _get_client_ip, check_identity_rate_limit as _check_identity_rate_limit, require_verified_agent
from agent_memory import memory_set, memory_get, memory_search, memory_clear, memory_list, register_agent, list_agents, marketplace_get_services
from agent_identity import generate_challenge, verify_challenge, verify_jwt, InvalidSignatureError, ChallengeExpiredError
from agent_network import get_reputation

agent_bp = Blueprint("agent", __name__)

# These will be set via init_agent_bp()
BATCH_HANDLERS = None
_skills_db_path = None
_skills_engine = None


def init_agent_bp(batch_handlers, skills_db_path, skills_engine):
    global BATCH_HANDLERS, _skills_db_path, _skills_engine
    BATCH_HANDLERS = batch_handlers
    _skills_db_path = skills_db_path
    _skills_engine = skills_engine


# ─── Helper ───────────────────────────────────────────────────────────────────

def _resolve_agent_id(data, require_verified=False):
    """Resolve agent_id from JWT (verified) or request body (unverified)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ey"):
        try:
            payload = verify_jwt(auth[7:])
            return payload["agent_id"], True
        except Exception:
            pass
    if require_verified:
        return "", False
    agent_id = data.get("agent_id", "")
    if agent_id and not _re.match(r'^[a-zA-Z0-9_\-]{1,64}$', agent_id):
        return "", False
    return agent_id, False


# ─── Agent Memory Endpoints ────────────────────────────────────────────────

@agent_bp.route("/memory/set", methods=["POST"])
def memory_set_route():
    data = request.get_json() or {}
    agent_id, verified = _resolve_agent_id(data, require_verified=True)
    if not verified:
        return jsonify({"error": "unauthorized", "message": "JWT required for memory writes. Use /agents/challenge + /agents/verify first."}), 401
    key = data.get("key", "")
    value = data.get("value")
    tags = data.get("tags", [])
    if not agent_id or not key or value is None:
        return jsonify({"error": "agent_id, key, and value required"}), 400
    result = memory_set(agent_id, key, value, tags if isinstance(tags, list) else [tags])
    log_payment("/memory/set", 0.01, request.remote_addr)
    return jsonify(agent_response({**result, "verified": verified}, "/memory/set"))


@agent_bp.route("/memory/get", methods=["POST"])
@require_verified_agent
def memory_get_route():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "")
    if agent_id and agent_id != request.agent["agent_id"]:
        return jsonify({"error": "forbidden", "message": "Cannot access another agent's memory"}), 403
    agent_id = agent_id or request.agent["agent_id"]
    verified = True
    key = data.get("key", "")
    if not key:
        return jsonify({"error": "key required"}), 400
    result = memory_get(agent_id, key)
    log_payment("/memory/get", 0.01, request.remote_addr)
    if not result:
        return jsonify({"error": "not_found", "agent_id": agent_id, "key": key}), 404
    return jsonify(agent_response({**result, "verified": verified}, "/memory/get"))


@agent_bp.route("/memory/search", methods=["POST"])
@require_verified_agent
def memory_search_route():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "")
    if agent_id and agent_id != request.agent["agent_id"]:
        return jsonify({"error": "forbidden", "message": "Cannot access another agent's memory"}), 403
    agent_id = agent_id or request.agent["agent_id"]
    verified = True
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "query required"}), 400
    results = memory_search(agent_id, query)
    log_payment("/memory/search", 0.02, request.remote_addr)
    return jsonify(agent_response({"agent_id": agent_id, "query": query, "results": results, "count": len(results), "verified": verified}, "/memory/search"))


@agent_bp.route("/memory/list", methods=["POST"])
@require_verified_agent
def memory_list_route():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "")
    if agent_id and agent_id != request.agent["agent_id"]:
        return jsonify({"error": "forbidden", "message": "Cannot access another agent's memory"}), 403
    agent_id = agent_id or request.agent["agent_id"]
    verified = True
    keys = memory_list(agent_id)
    log_payment("/memory/list", 0.01, request.remote_addr)
    return jsonify(agent_response({"agent_id": agent_id, "keys": keys, "count": len(keys), "verified": verified}, "/memory/list"))


@agent_bp.route("/memory/clear", methods=["POST"])
def memory_clear_route():
    data = request.get_json() or {}
    agent_id, verified = _resolve_agent_id(data, require_verified=True)
    if not verified:
        return jsonify({"error": "unauthorized", "message": "JWT required for memory clear. Use /agents/challenge + /agents/verify first."}), 401
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400
    deleted = memory_clear(agent_id)
    log_payment("/memory/clear", 0.01, request.remote_addr)
    return jsonify(agent_response({"agent_id": agent_id, "deleted": deleted, "verified": verified}, "/memory/clear"))


# ─── Agent Identity (wallet auth) ─────────────────────────────────────────

@agent_bp.route("/agents/challenge", methods=["POST"])
def agent_challenge():
    """Step 1: Request a challenge to prove wallet ownership."""
    _ip = _get_client_ip()
    if not _check_identity_rate_limit(_ip):
        return jsonify({"error": "rate_limited", "message": "Too many identity requests. Max 10/min."}), 429
    data = request.get_json() or {}
    wallet = data.get("wallet_address", "")
    if not wallet:
        return jsonify({"error": "wallet_address required"}), 400
    ch = generate_challenge(wallet)
    return jsonify(ch)


@agent_bp.route("/agents/verify", methods=["POST"])
def agent_verify():
    """Step 2: Submit signed challenge to get JWT."""
    _ip = _get_client_ip()
    if not _check_identity_rate_limit(_ip):
        return jsonify({"error": "rate_limited", "message": "Too many identity requests. Max 10/min."}), 429
    data = request.get_json() or {}
    nonce = data.get("nonce", "")
    signature = data.get("signature", "")
    chain = data.get("chain", "evm")
    if not nonce or not signature:
        return jsonify({"error": "nonce and signature required"}), 400
    try:
        result = verify_challenge(nonce, signature, chain)
        # Auto-register in agent registry if not exists
        try:
            register_agent(
                result["agent_id"],
                data.get("name", f"agent-{result['agent_id'][:8]}"),
                data.get("description", ""),
                data.get("capabilities", ""),
                data.get("endpoint", ""),
            )
        except Exception:
            pass
        return jsonify(result)
    except (InvalidSignatureError, ChallengeExpiredError) as e:
        return jsonify({"error": str(e)}), 401


@agent_bp.route("/agents/me", methods=["GET"])
def agent_me():
    """Get current agent profile (requires JWT)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ey"):
        return jsonify({"error": "JWT required. Use /agents/challenge + /agents/verify first."}), 401
    try:
        payload = verify_jwt(auth[7:])
        return jsonify(payload)
    except Exception:
        return jsonify({"error": "Invalid or expired token"}), 401


# ─── Agent Registry (free) ────────────────────────────────────────────────

@agent_bp.route("/agents/register", methods=["POST"])
def agents_register():
    data = request.get_json() or {}
    agent_id, verified = _resolve_agent_id(data, require_verified=True)
    if not verified:
        return jsonify({"error": "unauthorized", "message": "JWT required to register agents. Use /agents/challenge + /agents/verify first."}), 401
    name = data.get("name", "")
    description = data.get("description", "")
    capabilities = data.get("capabilities", [])
    endpoint = data.get("endpoint")
    if not agent_id or not name:
        return jsonify({"error": "agent_id and name required"}), 400
    result = register_agent(agent_id, name, description, capabilities, endpoint)
    return jsonify({"registered": True, "agent_id": agent_id, "listing": f"https://api.aipaygen.com/agents"})


@agent_bp.route("/agents", methods=["GET"])
def agents_list():
    agents = list_agents()
    return jsonify({"agents": agents, "count": len(agents), "_meta": {"endpoint": "/agents", "ts": datetime.utcnow().isoformat() + "Z"}})


@agent_bp.route("/agents/search", methods=["GET"])
def agents_search():
    """Search agents by capability, name, or description."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    agents = list_agents()
    results = []
    q_lower = q.lower()
    for a in agents:
        score = 0
        if q_lower in (a.get("name", "") or "").lower():
            score += 3
        caps = a.get("capabilities", "")
        caps_str = ",".join(caps) if isinstance(caps, list) else (caps or "")
        if q_lower in caps_str.lower():
            score += 2
        if q_lower in (a.get("description", "") or "").lower():
            score += 1
        if score > 0:
            results.append({**a, "_relevance": score})
    results.sort(key=lambda x: x["_relevance"], reverse=True)
    return jsonify({"query": q, "results": results[:20]})


@agent_bp.route("/agents/<agent_id>/portfolio", methods=["GET"])
def agent_portfolio(agent_id):
    """Get agent's full portfolio: reputation, marketplace listings."""
    rep = get_reputation(agent_id)
    all_listings, _ = marketplace_get_services(per_page=200)
    agent_listings = [l for l in all_listings if l.get("agent_id") == agent_id]
    return jsonify({
        "agent_id": agent_id,
        "reputation": rep,
        "marketplace_listings": agent_listings,
        "verified": False,
    })


# ─── Chain Endpoint ───────────────────────────────────────────────────────

def _build_chain_handlers():
    """Build the chain handlers dict. Called lazily to avoid circular imports."""
    from routes.ai_tools import (
        research_inner, summarize_inner, analyze_inner, translate_inner,
        sentiment_inner, keywords_inner, classify_inner, rewrite_inner,
        extract_inner, qa_inner, compare_inner, outline_inner,
        diagram_inner, json_schema_inner, workflow_inner,
    )
    return {
        "research": lambda p: research_inner(p.get("query", ""), model=p.get("model", "claude-haiku")),
        "summarize": lambda p: summarize_inner(p.get("text", ""), p.get("format", "bullets"), model=p.get("model", "claude-haiku")),
        "analyze": lambda p: analyze_inner(p.get("text", ""), p.get("question", ""), model=p.get("model", "claude-haiku")),
        "translate": lambda p: translate_inner(p.get("text", ""), p.get("language", "English"), model=p.get("model", "claude-haiku")),
        "sentiment": lambda p: sentiment_inner(p.get("text", ""), model=p.get("model", "claude-haiku")),
        "keywords": lambda p: keywords_inner(p.get("text", ""), int(p.get("n", 10)), model=p.get("model", "claude-haiku")),
        "classify": lambda p: classify_inner(p.get("text", ""), p.get("categories", []), model=p.get("model", "claude-haiku")),
        "rewrite": lambda p: rewrite_inner(p.get("text", ""), p.get("audience", "general"), p.get("tone", "professional"), model=p.get("model", "claude-haiku")),
        "extract": lambda p: extract_inner(p.get("text", ""), p.get("schema_desc", ""), p.get("fields", []), model=p.get("model", "claude-haiku")),
        "qa": lambda p: qa_inner(p.get("context", ""), p.get("question", ""), model=p.get("model", "claude-haiku")),
        "compare": lambda p: compare_inner(p.get("text_a", ""), p.get("text_b", ""), p.get("focus", ""), model=p.get("model", "claude-haiku")),
        "outline": lambda p: outline_inner(p.get("topic", ""), int(p.get("depth", 2)), model=p.get("model", "claude-haiku")),
        "diagram": lambda p: diagram_inner(p.get("description", ""), p.get("diagram_type", "flowchart"), model=p.get("model", "claude-haiku")),
        "json_schema": lambda p: json_schema_inner(p.get("description", ""), p.get("example", {}), model=p.get("model", "claude-haiku")),
        "workflow": lambda p: workflow_inner(p.get("goal", ""), p.get("available_data", {}), model=p.get("model", "claude-sonnet")),
    }


_CHAIN_HANDLERS = None


def _get_chain_handlers():
    global _CHAIN_HANDLERS
    if _CHAIN_HANDLERS is None:
        _CHAIN_HANDLERS = _build_chain_handlers()
    return _CHAIN_HANDLERS


@agent_bp.route("/chain", methods=["POST"])
def chain_endpoint():
    """Chain up to 5 AI operations in sequence. Output of each step feeds the next."""
    data = request.get_json() or {}
    steps = data.get("steps", [])
    if not steps:
        return jsonify({"error": "steps array required"}), 400
    if len(steps) > 5:
        return jsonify({"error": "maximum 5 steps per chain"}), 400

    chain_handlers = _get_chain_handlers()
    results = []
    context = {}  # carries forward between steps

    for i, step in enumerate(steps):
        name = step.get("action")
        if not name or name not in chain_handlers:
            return jsonify({
                "error": f"step {i}: unknown action '{name}'",
                "available": list(chain_handlers.keys())
            }), 400

        # Allow steps to reference previous result via {{prev_result}}
        params = step.get("params", {})
        if context.get("last_result"):
            for k, v in params.items():
                if isinstance(v, str) and "{{prev_result}}" in v:
                    params[k] = v.replace("{{prev_result}}", str(context["last_result"]))

        try:
            out = chain_handlers[name](params)
            step_result = {"step": i + 1, "action": name, "result": out}
            results.append(step_result)
            # Extract text result for next step context
            if isinstance(out, dict):
                context["last_result"] = out.get("result") or out.get("text") or out.get("summary") or str(out)
            else:
                context["last_result"] = str(out)
        except Exception as e:
            return jsonify({"error": f"step {i} ({name}) failed: {str(e)}", "completed_steps": results}), 500

    log_payment("/chain", 0.25, request.remote_addr)
    return jsonify(agent_response({
        "steps_completed": len(results),
        "chain": results,
        "final_result": results[-1]["result"] if results else None,
    }, "/chain"))


# ── ReAct Agent — autonomous reasoning endpoint ──────────────────────────────

@agent_bp.route("/agent", methods=["POST"])
def agent_endpoint():
    """Autonomous AI agent that reasons through complex tasks using tools."""
    from react_agent import ReActAgent, make_tool_handler
    from agent_memory import memory_search, memory_set

    data = request.get_json() or {}
    task = data.get("task", "")
    if not task:
        return jsonify({"error": "task required", "hint": 'POST {"task": "your task description"}'}), 400

    agent_id = data.get("agent_id", "")
    max_cost = float(data.get("max_cost_usd", 1.0))
    max_steps = min(int(data.get("max_steps", 10)), 20)
    model = data.get("model", "auto")

    tool_handler = make_tool_handler(
        batch_handlers=BATCH_HANDLERS,
        memory_search_fn=memory_search if agent_id else None,
        memory_set_fn=memory_set if agent_id else None,
        skills_db_path=_skills_db_path,
        agent_id=agent_id,
        skills_search_engine=_skills_engine,
        call_model_fn=call_model,
    )

    memory_fns = {}
    if agent_id:
        memory_fns = {"search": memory_search, "set": memory_set}

    agent = ReActAgent(
        call_model_fn=call_model,
        tool_handler_fn=tool_handler,
        memory_fns=memory_fns,
    )

    result = agent.run(task=task, max_steps=max_steps, max_cost_usd=max_cost, model=model, agent_id=agent_id)
    log_payment("/agent", result.get("total_cost_usd", 0.05), request.remote_addr)
    return jsonify(agent_response(result, "/agent"))


@agent_bp.route("/agent/stream", methods=["POST"])
def agent_stream_endpoint():
    """Streaming autonomous agent — returns SSE events as the agent reasons."""
    from react_agent import ReActAgent, make_tool_handler
    from agent_memory import memory_search, memory_set

    data = request.get_json() or {}
    task = data.get("task", "")
    if not task:
        return jsonify({"error": "task required"}), 400

    agent_id = data.get("agent_id", "")
    max_cost = float(data.get("max_cost_usd", 1.0))
    max_steps = min(int(data.get("max_steps", 10)), 20)
    model = data.get("model", "auto")

    tool_handler = make_tool_handler(
        batch_handlers=BATCH_HANDLERS,
        memory_search_fn=memory_search if agent_id else None,
        memory_set_fn=memory_set if agent_id else None,
        skills_db_path=_skills_db_path,
        agent_id=agent_id,
        skills_search_engine=_skills_engine,
        call_model_fn=call_model,
    )
    memory_fns = {"search": memory_search, "set": memory_set} if agent_id else {}
    agent = ReActAgent(call_model_fn=call_model, tool_handler_fn=tool_handler, memory_fns=memory_fns)

    def generate():
        for event in agent.run_stream(task=task, max_steps=max_steps, max_cost_usd=max_cost, model=model, agent_id=agent_id):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
