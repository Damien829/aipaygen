"""A2A Commerce API routes — agent-to-agent discovery, RFQs, transactions."""
from flask import Blueprint, request, jsonify
from helpers import require_api_key, rate_limit
import a2a_engine

a2a_bp = Blueprint("a2a", __name__)


@a2a_bp.route("/a2a/stats")
def a2a_stats():
    """Network-wide A2A stats."""
    return jsonify(a2a_engine.a2a_stats())


@a2a_bp.route("/a2a/discover")
def a2a_discover():
    """Discover A2A-enabled agents by capability."""
    capability = request.args.get("capability")
    max_price = request.args.get("max_price", type=float)
    limit = request.args.get("limit", 20, type=int)
    agents = a2a_engine.discover_agents(capability=capability, max_price=max_price, limit=limit)
    return jsonify(agents)


@a2a_bp.route("/a2a/register", methods=["POST"])
@require_api_key
@rate_limit(60)
def a2a_register():
    """Register agent for A2A commerce."""
    data = request.get_json(force=True)
    result = a2a_engine.register_a2a_agent(
        agent_id=request.agent_id,
        agent_name=data.get("agent_name", ""),
        capabilities=data.get("capabilities", []),
        endpoint=data.get("endpoint", ""),
        min_price_usd=data.get("min_price_usd", 0.01),
        auto_accept=data.get("auto_accept", True),
        negotiation_enabled=data.get("negotiation_enabled", False),
    )
    return jsonify(result)


@a2a_bp.route("/a2a/rfq", methods=["POST"])
@require_api_key
@rate_limit(60)
def a2a_create_rfq():
    """Create a Request for Quote."""
    data = request.get_json(force=True)
    result = a2a_engine.create_rfq(
        requester_id=request.agent_id,
        title=data.get("title", ""),
        description=data.get("description", ""),
        capabilities_needed=data.get("capabilities_needed", []),
        budget_usd=data.get("budget_usd", 0.0),
        budget_type=data.get("budget_type", "per_call"),
        sla_requirements=data.get("sla_requirements"),
    )
    return jsonify(result), 201


@a2a_bp.route("/a2a/rfq/open")
def a2a_open_rfqs():
    """List open RFQs."""
    capability = request.args.get("capability")
    limit = request.args.get("limit", 20, type=int)
    return jsonify(a2a_engine.get_open_rfqs(capability=capability, limit=limit))


@a2a_bp.route("/a2a/rfq/<rfq_id>")
def a2a_rfq_detail(rfq_id):
    """Get RFQ detail with responses."""
    from a2a_engine import _conn
    import json
    with _conn() as c:
        row = c.execute("SELECT * FROM rfq_requests WHERE id = ?", (rfq_id,)).fetchone()
    if not row:
        return jsonify({"error": "RFQ not found"}), 404
    rfq = dict(row)
    rfq["capabilities_needed"] = json.loads(rfq.get("capabilities_needed") or "[]")
    rfq["sla_requirements"] = json.loads(rfq.get("sla_requirements") or "{}")
    rfq["responses"] = a2a_engine.get_rfq_responses(rfq_id)
    return jsonify(rfq)


@a2a_bp.route("/a2a/rfq/<rfq_id>/respond", methods=["POST"])
@require_api_key
@rate_limit(60)
def a2a_respond_rfq(rfq_id):
    """Respond to an RFQ."""
    data = request.get_json(force=True)
    result = a2a_engine.respond_to_rfq(
        rfq_id=rfq_id,
        responder_id=request.agent_id,
        price_usd=data.get("price_usd", 0.0),
        price_type=data.get("price_type", "per_call"),
        sla_offered=data.get("sla_offered"),
        message=data.get("message", ""),
    )
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result), 201


@a2a_bp.route("/a2a/rfq/<rfq_id>/accept", methods=["POST"])
@require_api_key
def a2a_accept_rfq(rfq_id):
    """Accept an RFQ response."""
    data = request.get_json(force=True)
    result = a2a_engine.accept_rfq_response(rfq_id, data.get("response_id", ""))
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@a2a_bp.route("/a2a/transactions")
def a2a_transactions():
    """Transaction feed."""
    buyer_id = request.args.get("buyer_id")
    seller_id = request.args.get("seller_id")
    limit = request.args.get("limit", 50, type=int)
    return jsonify(a2a_engine.get_a2a_transactions(buyer_id=buyer_id, seller_id=seller_id, limit=limit))


@a2a_bp.route("/a2a/transact", methods=["POST"])
@require_api_key
@rate_limit(60)
def a2a_transact():
    """Record a direct A2A transaction."""
    data = request.get_json(force=True)
    result = a2a_engine.record_a2a_transaction(
        buyer_id=request.agent_id,
        seller_id=data.get("seller_id", ""),
        amount_usd=data.get("amount_usd", 0.0),
        service_endpoint=data.get("service_endpoint", ""),
    )
    return jsonify(result), 201


@a2a_bp.route("/a2a/leaderboard")
def a2a_leaderboard():
    """Top A2A earners."""
    limit = request.args.get("limit", 20, type=int)
    return jsonify(a2a_engine.a2a_leaderboard(limit=limit))
