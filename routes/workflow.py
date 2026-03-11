"""Workflow engine route — chain multiple AI tools in sequence."""

from flask import Blueprint, request, jsonify
from workflow_engine import validate_workflow, execute_workflow
from helpers import require_api_key

workflow_bp = Blueprint("workflow_engine", __name__)


@workflow_bp.route("/workflow/run", methods=["POST"])
@require_api_key
def run_workflow():
    data = request.get_json(silent=True) or {}
    steps = data.get("steps", [])
    errors = validate_workflow(steps)
    if errors:
        return jsonify({"error": "invalid_workflow", "details": errors}), 400

    from flask import current_app
    client = current_app.test_client()
    result = execute_workflow(steps, app_client=client)
    return jsonify(result)
