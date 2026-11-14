"""Workflow CRUD and marketplace endpoints."""
import logging
from flask import Blueprint, request, jsonify
from helpers import require_admin
from workflow_db import (
    create_workflow, get_workflow, list_user_workflows, update_workflow,
    delete_workflow, increment_run_count, list_marketplace, rate_workflow,
    record_purchase,
)

_log = logging.getLogger(__name__)
workflows_bp = Blueprint("workflows", __name__)

# Shared reference set by init
_chain_fn = None

def init_workflows_bp(chain_fn=None):
    global _chain_fn
    _chain_fn = chain_fn


# ── User Workflow CRUD ─────────────────────────────────────────────────────────

@workflows_bp.route("/workflows", methods=["POST"])
def create():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    steps = data.get("steps", [])
    if not steps or not isinstance(steps, list):
        return jsonify({"error": "steps array required"}), 400
    wallet = request.environ.get("X_WALLET", data.get("wallet", "anonymous"))
    wf_id = create_workflow(
        creator_wallet=wallet,
        name=name,
        description=data.get("description", ""),
        steps=steps,
        category=data.get("category", "general"),
    )
    return jsonify({"id": wf_id, "name": name, "created": True})


@workflows_bp.route("/workflows", methods=["GET"])
def list_mine():
    wallet = request.args.get("wallet", request.environ.get("X_WALLET", ""))
    if not wallet:
        return jsonify({"error": "wallet param required"}), 400
    wfs = list_user_workflows(wallet)
    return jsonify({"workflows": wfs, "count": len(wfs)})


@workflows_bp.route("/workflows/<int:wf_id>", methods=["GET"])
def get_one(wf_id):
    wf = get_workflow(wf_id)
    if not wf:
        return jsonify({"error": "not_found"}), 404
    return jsonify(wf)


@workflows_bp.route("/workflows/<int:wf_id>", methods=["PUT"])
def update(wf_id):
    data = request.get_json() or {}
    wallet = request.environ.get("X_WALLET", data.get("wallet", ""))
    if not wallet:
        return jsonify({"error": "wallet required"}), 400
    ok = update_workflow(wf_id, wallet, **{k: v for k, v in data.items() if k != "wallet"})
    if not ok:
        return jsonify({"error": "not_found or not owner"}), 404
    return jsonify({"updated": True})


@workflows_bp.route("/workflows/<int:wf_id>", methods=["DELETE"])
def delete(wf_id):
    data = request.get_json() or {}
    wallet = request.environ.get("X_WALLET", data.get("wallet", ""))
    delete_workflow(wf_id, wallet)
    return jsonify({"deleted": True})


@workflows_bp.route("/workflows/<int:wf_id>/run", methods=["POST"])
def run_workflow(wf_id):
    wf = get_workflow(wf_id)
    if not wf:
        return jsonify({"error": "not_found"}), 404
    data = request.get_json() or {}
    steps = wf["steps"]
    # Replace template variables in steps with user input
    user_input = data.get("input", "")
    results = []
    prev_output = user_input
    for i, step in enumerate(steps):
        tool = step.get("tool", "")
        step_input = step.get("input", {})
        # Replace {{input}} and {{prev}} placeholders
        for k, v in step_input.items():
            if isinstance(v, str):
                step_input[k] = v.replace("{{input}}", user_input).replace("{{prev}}", str(prev_output))
        try:
            from helpers import call_llm
            result, err = call_llm(
                [{"role": "user", "content": str(step_input.get("input", step_input.get("text", prev_output)))}],
                endpoint=f"/workflows/{wf_id}/step/{i}",
                max_tokens=1024,
            )
            if err:
                results.append({"step": i, "tool": tool, "error": err})
                break
            prev_output = result.get("text", "")
            results.append({"step": i, "tool": tool, "output": prev_output})
        except Exception as e:
            results.append({"step": i, "tool": tool, "error": str(e)})
            break
    increment_run_count(wf_id)
    return jsonify({
        "workflow_id": wf_id,
        "name": wf["name"],
        "steps_run": len(results),
        "results": results,
        "final_output": prev_output,
    })


@workflows_bp.route("/workflows/<int:wf_id>/publish", methods=["POST"])
def publish(wf_id):
    data = request.get_json() or {}
    wallet = request.environ.get("X_WALLET", data.get("wallet", ""))
    price = float(data.get("price_usdc", 0))
    ok = update_workflow(wf_id, wallet, is_public=1, price_usdc=price)
    if not ok:
        return jsonify({"error": "not_found or not owner"}), 404
    return jsonify({"published": True, "price_usdc": price})


# ── Marketplace ────────────────────────────────────────────────────────────────

@workflows_bp.route("/marketplace/workflows", methods=["GET"])
def marketplace_browse():
    category = request.args.get("category", "")
    sort = request.args.get("sort", "popular")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    wfs = list_marketplace(category=category or None, sort=sort, limit=limit, offset=offset)
    return jsonify({"workflows": wfs, "count": len(wfs)})


@workflows_bp.route("/marketplace/workflows/<int:wf_id>", methods=["GET"])
def marketplace_detail(wf_id):
    wf = get_workflow(wf_id)
    if not wf or not wf.get("is_public"):
        return jsonify({"error": "not_found"}), 404
    return jsonify(wf)


@workflows_bp.route("/marketplace/workflows/<int:wf_id>/buy", methods=["POST"])
def marketplace_buy(wf_id):
    wf = get_workflow(wf_id)
    if not wf or not wf.get("is_public"):
        return jsonify({"error": "not_found"}), 404
    if wf["price_usdc"] <= 0:
        return jsonify({"purchased": True, "price": 0, "message": "Free workflow"})
    data = request.get_json() or {}
    buyer = data.get("wallet", request.environ.get("X_WALLET", ""))
    tx_hash = data.get("tx_hash", "")
    shares = record_purchase(wf_id, buyer, wf["price_usdc"], tx_hash)
    return jsonify({"purchased": True, "price_usdc": wf["price_usdc"], **shares})


@workflows_bp.route("/marketplace/workflows/<int:wf_id>/rate", methods=["POST"])
def marketplace_rate(wf_id):
    data = request.get_json() or {}
    wallet = request.environ.get("X_WALLET", data.get("wallet", ""))
    stars = int(data.get("stars", 0))
    if not 1 <= stars <= 5:
        return jsonify({"error": "stars must be 1-5"}), 400
    rate_workflow(wf_id, wallet, stars, data.get("comment", ""))
    return jsonify({"rated": True, "stars": stars})
