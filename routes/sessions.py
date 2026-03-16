"""Session routes — create, call with context, history, delete."""

import json
import time as _time

from flask import Blueprint, request, jsonify
from sessions import (
    create_session, get_session, update_session_context,
    delete_session, add_session_call, get_session_history,
    get_session_context_messages,
)
from helpers import require_api_key, log_payment, agent_response

import logging
_log = logging.getLogger(__name__)

sessions_bp = Blueprint("sessions", __name__)

# Will be set via init_sessions_bp()
_batch_handlers = None


def init_sessions_bp(batch_handlers):
    global _batch_handlers
    _batch_handlers = batch_handlers


# ── POST /session/create ─────────────────────────────────────────────────────

@sessions_bp.route("/session/create", methods=["POST"])
@require_api_key
def create_session_route():
    """Create a new session. Returns session_id. Sessions auto-expire after ttl_hours (default 1)."""
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id", "anonymous")
    context = data.get("context", {})
    ttl = min(data.get("ttl_hours", 1), 24)  # max 24h
    sid = create_session(agent_id=agent_id, context=context, ttl_hours=ttl)
    return jsonify({"session_id": sid, "ttl_hours": ttl, "agent_id": agent_id})


# ── POST /session/start (legacy compat) ─────────────────────────────────────

@sessions_bp.route("/session/start", methods=["POST"])
@require_api_key
def start_session():
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id", "anonymous")
    context = data.get("context", {})
    ttl = data.get("ttl_hours", 24)
    sid = create_session(agent_id=agent_id, context=context, ttl_hours=ttl)
    return jsonify({"session_id": sid, "ttl_hours": ttl})


# ── POST /session/<id>/call ──────────────────────────────────────────────────

@sessions_bp.route("/session/<session_id>/call", methods=["POST"])
@require_api_key
def session_call(session_id):
    """Execute a tool call within a session. Session history is injected as context for AI tools."""
    sess = get_session(session_id)
    if not sess:
        return jsonify({"error": "session_not_found"}), 404

    data = request.get_json(silent=True) or {}
    tool = data.get("tool", "").lstrip("/")
    inp = data.get("input", {})

    if not tool:
        return jsonify({"error": "tool required"}), 400

    if _batch_handlers is None or tool not in _batch_handlers:
        valid = list(_batch_handlers.keys()) if _batch_handlers else []
        return jsonify({"error": f"unknown tool '{tool}'", "valid_tools": valid[:20]}), 400

    # Inject session context into AI input
    session_context = get_session_context_messages(session_id, limit=10)
    if session_context:
        # Add session history as context for tools that accept it
        if "context" not in inp or not inp["context"]:
            inp["context"] = session_context
        else:
            inp["context"] = session_context + "\n\n" + str(inp["context"])

    t0 = _time.time()
    try:
        result = _batch_handlers[tool](inp)
        elapsed = int((_time.time() - t0) * 1000)
    except Exception:
        elapsed = int((_time.time() - t0) * 1000)
        _log.exception("session call %s failed in session %s", tool, session_id)
        result = {"error": "Execution failed"}

    # Record in session history
    add_session_call(session_id, tool, data.get("input", {}), result, time_ms=elapsed)

    log_payment(f"/session/{session_id}/call:{tool}", 0.01, request.remote_addr)
    return jsonify(agent_response({
        "session_id": session_id,
        "tool": tool,
        "result": result,
        "time_ms": elapsed,
    }, "/session/call"))


# ── GET /session/<id>/history ────────────────────────────────────────────────

@sessions_bp.route("/session/<session_id>/history", methods=["GET"])
@require_api_key
def session_history(session_id):
    """Return all calls made in this session."""
    sess = get_session(session_id)
    if not sess:
        return jsonify({"error": "session_not_found"}), 404

    limit = min(int(request.args.get("limit", 50)), 200)
    history = get_session_history(session_id, limit=limit)
    return jsonify({
        "session_id": session_id,
        "agent_id": sess["agent_id"],
        "call_count": len(history),
        "history": history,
    })


# ── DELETE /session/<id> ─────────────────────────────────────────────────────

@sessions_bp.route("/session/<session_id>", methods=["DELETE"])
@require_api_key
def delete_session_route(session_id):
    """End a session and delete all its history."""
    sess = get_session(session_id)
    if not sess:
        return jsonify({"error": "session_not_found"}), 404
    delete_session(session_id)
    return jsonify({"deleted": True, "session_id": session_id})


# ── GET /session/<id> (resume / inspect) ─────────────────────────────────────

@sessions_bp.route("/session/<session_id>", methods=["GET"])
@require_api_key
def resume_session(session_id):
    s = get_session(session_id)
    if not s:
        return jsonify({"error": "session_not_found"}), 404
    return jsonify(s)


# ── PUT /session/<id>/context ────────────────────────────────────────────────

@sessions_bp.route("/session/<session_id>/context", methods=["PUT"])
@require_api_key
def update_context(session_id):
    s = get_session(session_id)
    if not s:
        return jsonify({"error": "session_not_found"}), 404
    data = request.get_json(silent=True) or {}
    new_context = data.get("context", {})
    merged = {**s["context"], **new_context}
    update_session_context(session_id, merged)
    return jsonify({"session_id": session_id, "context": merged})
