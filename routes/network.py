from flask import Blueprint, request, jsonify
from agent_network import (
    send_message, get_inbox, mark_read, broadcast_message,
    add_knowledge, search_knowledge, get_trending_topics, vote_knowledge,
    submit_task, browse_tasks, claim_task, complete_task, get_task,
)
from helpers import log_payment, agent_response

network_bp = Blueprint("network", __name__)


# -- Messaging ----------------------------------------------------------------

@network_bp.route("/message/send", methods=["POST"])
def message_send():
    data = request.get_json() or {}
    from_agent = data.get("from_agent", "")
    to_agent = data.get("to_agent", "")
    body = data.get("body", "")
    if not from_agent or not to_agent or not body:
        return jsonify({"error": "from_agent, to_agent, and body required"}), 400
    result = send_message(from_agent, to_agent, data.get("subject", ""), body, data.get("thread_id"))
    log_payment("/message/send", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/message/send"))


@network_bp.route("/message/inbox/<agent_id>", methods=["GET"])
def message_inbox(agent_id):
    unread_only = request.args.get("unread_only", "0") in ("1", "true", "yes")
    messages = get_inbox(agent_id, unread_only=unread_only)
    return jsonify({"agent_id": agent_id, "messages": messages, "count": len(messages), "_meta": {"free": True}})


@network_bp.route("/message/reply", methods=["POST"])
def message_reply():
    data = request.get_json() or {}
    msg_id = data.get("msg_id", "")
    from_agent = data.get("from_agent", "")
    body = data.get("body", "")
    if not msg_id or not from_agent or not body:
        return jsonify({"error": "msg_id, from_agent, and body required"}), 400
    # Find original to get thread_id and reply-to agent
    msgs = get_inbox("__lookup__")  # we'll just use send_message with thread_id
    result = send_message(from_agent, data.get("to_agent", ""), data.get("subject", "Re:"), body, thread_id=msg_id)
    log_payment("/message/reply", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/message/reply"))


@network_bp.route("/message/broadcast", methods=["POST"])
def message_broadcast():
    data = request.get_json() or {}
    from_agent = data.get("from_agent", "")
    body = data.get("body", "")
    if not from_agent or not body:
        return jsonify({"error": "from_agent and body required"}), 400
    result = broadcast_message(from_agent, data.get("subject", ""), body)
    log_payment("/message/broadcast", 0.02, request.remote_addr)
    return jsonify(agent_response({"broadcast": True, "result": result}, "/message/broadcast"))


# -- Shared Knowledge Base -----------------------------------------------------

@network_bp.route("/knowledge/add", methods=["POST"])
def knowledge_add():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    content = data.get("content", "")
    author_agent = data.get("author_agent", "anonymous")
    if not topic or not content:
        return jsonify({"error": "topic and content required"}), 400
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    result = add_knowledge(topic, content, author_agent, tags)
    log_payment("/knowledge/add", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/knowledge/add"))


@network_bp.route("/knowledge/search", methods=["GET"])
def knowledge_search():
    q = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 10)), 50)
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    results = search_knowledge(q, limit=limit)
    return jsonify({"query": q, "results": results, "count": len(results), "_meta": {"free": True}})


@network_bp.route("/knowledge/trending", methods=["GET"])
def knowledge_trending():
    limit = min(int(request.args.get("limit", 10)), 50)
    topics = get_trending_topics(limit=limit)
    return jsonify({"trending": topics, "_meta": {"free": True}})


@network_bp.route("/knowledge/vote", methods=["POST"])
def knowledge_vote():
    data = request.get_json() or {}
    entry_id = data.get("entry_id", "")
    up = data.get("up", True)
    if not entry_id:
        return jsonify({"error": "entry_id required"}), 400
    result = vote_knowledge(entry_id, up=bool(up))
    return jsonify({**result, "_meta": {"free": True}})


# -- Task Broker ---------------------------------------------------------------

@network_bp.route("/task/submit", methods=["POST"])
def task_submit():
    data = request.get_json() or {}
    posted_by = data.get("posted_by", "")
    title = data.get("title", "")
    description = data.get("description", "")
    if not posted_by or not title or not description:
        return jsonify({"error": "posted_by, title, and description required"}), 400
    result = submit_task(
        posted_by, title, description,
        skills_needed=data.get("skills_needed", []),
        reward_usd=float(data.get("reward_usd", 0.0)),
    )
    log_payment("/task/submit", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/task/submit"))


@network_bp.route("/task/browse", methods=["GET"])
def task_browse():
    status = request.args.get("status", "open")
    skill = request.args.get("skill")
    limit = min(int(request.args.get("limit", 20)), 100)
    tasks = browse_tasks(status=status, skill=skill, limit=limit)
    return jsonify({"tasks": tasks, "count": len(tasks), "_meta": {"free": True}})


@network_bp.route("/task/claim", methods=["POST"])
def task_claim():
    data = request.get_json() or {}
    task_id = data.get("task_id", "")
    agent_id = data.get("agent_id", "")
    if not task_id or not agent_id:
        return jsonify({"error": "task_id and agent_id required"}), 400
    success = claim_task(task_id, agent_id)
    return jsonify({"task_id": task_id, "claimed": success, "_meta": {"free": True}})


@network_bp.route("/task/complete", methods=["POST"])
def task_complete():
    data = request.get_json() or {}
    task_id = data.get("task_id", "")
    agent_id = data.get("agent_id", "")
    result = data.get("result", "")
    if not task_id or not agent_id or not result:
        return jsonify({"error": "task_id, agent_id, and result required"}), 400
    success = complete_task(task_id, agent_id, result)
    log_payment("/task/complete", 0.01, request.remote_addr)
    return jsonify(agent_response({"task_id": task_id, "completed": success}, "/task/complete"))


@network_bp.route("/task/<task_id>", methods=["GET"])
def task_get(task_id):
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task_not_found"}), 404
    return jsonify({**task, "_meta": {"free": True}})
