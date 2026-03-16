"""Webhook testing UI and new API routes (test-event, deliveries)."""
import logging

from flask import Blueprint, request, jsonify, render_template
from helpers import require_api_key

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks_ui", __name__)


@webhooks_bp.route("/webhooks/test")
def webhook_test_page():
    from routes.meta import NAV_HTML, FOOTER_HTML
    return render_template("webhook_test.html", nav=NAV_HTML, footer=FOOTER_HTML)


@webhooks_bp.route("/webhooks/test-event", methods=["POST"])
@require_api_key
def webhook_test_event():
    from webhook_dispatch import dispatch_test_event
    data = request.get_json(silent=True) or {}
    event_type = data.get("event", "low_balance")
    payload = data.get("payload", {})
    count = dispatch_test_event(event_type, request.api_key, payload)
    return jsonify({"dispatched_to": count, "event": event_type})


@webhooks_bp.route("/webhooks/deliveries")
@require_api_key
def webhook_deliveries():
    from webhook_dispatch import get_deliveries
    limit = min(int(request.args.get("limit", 50)), 200)
    deliveries = get_deliveries(request.api_key, limit)
    return jsonify({"deliveries": deliveries})
