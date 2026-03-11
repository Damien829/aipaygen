from flask import Blueprint, request, jsonify
from sessions import create_session, get_session, update_session_context
from helpers import require_api_key

sessions_bp = Blueprint("sessions", __name__)

@sessions_bp.route("/session/start", methods=["POST"])
@require_api_key
def start_session():
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id", "anonymous")
    context = data.get("context", {})
    ttl = data.get("ttl_hours", 24)
    sid = create_session(agent_id=agent_id, context=context, ttl_hours=ttl)
    return jsonify({"session_id": sid, "ttl_hours": ttl})

@sessions_bp.route("/session/<session_id>", methods=["GET"])
@require_api_key
def resume_session(session_id):
    s = get_session(session_id)
    if not s:
        return jsonify({"error": "session_not_found"}), 404
    return jsonify(s)

@sessions_bp.route("/session/<session_id>/context", methods=["PUT"])
@require_api_key
def update_context(session_id):
    s = get_session(session_id)
    if not s:
        return jsonify({"error": "session_not_found"}), 404
    data = request.get_json(silent=True) or {}
    new_context = data.get("context", {})
    # Merge with existing
    merged = {**s["context"], **new_context}
    update_session_context(session_id, merged)
    return jsonify({"session_id": session_id, "context": merged})
