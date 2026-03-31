"""
SaaS Starter Kit — Flask Application Template
A production-ready API backend with auth, billing, and admin tools.

Run:
    pip install -r requirements.txt
    cp env.template .env  # fill in your values
    python app_template.py
"""

import gzip
import io
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response

load_dotenv()

from auth import (
    init_db,
    generate_key,
    validate_key,
    get_key_status,
    topup_key,
    deduct,
    revoke_key,
    check_rate_limit,
    create_checkout,
    create_subscription_checkout,
    handle_webhook,
    require_api_key,
    require_admin,
    _check_checkout_rate,
)

# ── App Configuration ────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB max body
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(32).hex()

APP_NAME = os.getenv("APP_NAME", "MySaaS")
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")

# ── Logging ──────────────────────────────────────────────────────────────────


class _RequestIdFilter(logging.Filter):
    def filter(self, record):
        try:
            record.request_id = getattr(request, "_request_id", "-")
        except RuntimeError:
            record.request_id = "-"
        return True


handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(request_id)s] %(message)s"
))
handler.addFilter(_RequestIdFilter())
app.logger.handlers = [handler]
app.logger.setLevel(logging.INFO)
logging.root.handlers = [handler]
logging.root.setLevel(logging.INFO)
logger = app.logger

# ── Middleware ────────────────────────────────────────────────────────────────


@app.before_request
def before_request():
    """Assign a unique request ID and start timer."""
    request._request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request._start_time = time.time()


@app.after_request
def after_request(response):
    """Add standard headers: CORS, request ID, timing, gzip compression."""
    # CORS — restrict in production
    origin = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Admin-Key, X-Request-ID"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"

    # Request tracing
    response.headers["X-Request-ID"] = getattr(request, "_request_id", "-")
    elapsed = time.time() - getattr(request, "_start_time", time.time())
    response.headers["X-Response-Time"] = f"{elapsed:.3f}s"

    # Gzip compression for responses > 500 bytes
    if (
        response.status_code == 200
        and not response.is_streamed
        and "gzip" in request.headers.get("Accept-Encoding", "")
        and response.content_length
        and response.content_length > 500
    ):
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
            gz.write(response.get_data())
        response.set_data(buf.getvalue())
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = len(response.get_data())

    return response


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(500)
def internal_error(e):
    logger.error("Internal error: %s", e)
    return jsonify({"error": "Internal server error"}), 500


# ── Health & Info ────────────────────────────────────────────────────────────


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "app": APP_NAME, "time": datetime.now(timezone.utc).isoformat()})


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "app": APP_NAME,
        "docs": f"{BASE_URL}/docs",
        "health": f"{BASE_URL}/health",
        "version": "1.0.0",
    })


# ── API Key Management ───────────────────────────────────────────────────────


@app.route("/api/keys/generate", methods=["POST"])
def api_generate_key():
    """Generate a new API key. Optionally pass {"label": "my-app"}."""
    data = request.get_json() or {}
    label = str(data.get("label", ""))[:60]
    result = generate_key(label=label, source="api")
    return jsonify(result), 201


@app.route("/api/keys/status", methods=["GET"])
@require_api_key(cost=0.0)
def api_key_status():
    """Check your API key balance and usage."""
    status = get_key_status(request.api_key)
    if not status:
        return jsonify({"error": "Key not found"}), 404
    return jsonify(status)


@app.route("/api/keys/revoke", methods=["POST"])
@require_api_key(cost=0.0)
def api_revoke_key():
    """Deactivate your API key permanently."""
    revoke_key(request.api_key)
    return jsonify({"revoked": True})


# ── Billing ──────────────────────────────────────────────────────────────────


@app.route("/api/billing/checkout", methods=["POST"])
def api_checkout():
    """Create a Stripe checkout session for one-time credit purchase.
    Body: {"amount": 10, "email": "user@example.com", "existing_key": "apk_..."}
    """
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
    if ip and _check_checkout_rate(ip):
        return jsonify({"error": "Too many checkout attempts. Wait a few minutes."}), 429

    data = request.get_json() or {}
    amount = data.get("amount")
    if amount is None:
        return jsonify({"error": "amount required", "allowed": [1, 5, 10, 20, 50, 100]}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    result = create_checkout(
        amount=amount,
        existing_key=data.get("existing_key", ""),
        email=data.get("email", ""),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/billing/subscribe", methods=["POST"])
def api_subscribe():
    """Create a Stripe subscription checkout session.
    Body: {"plan": "starter|pro|business", "email": "user@example.com"}
    """
    data = request.get_json() or {}
    plan = data.get("plan", "starter")

    price_ids = {
        "starter": os.getenv("STRIPE_PRICE_STARTER", ""),
        "pro": os.getenv("STRIPE_PRICE_PRO", ""),
        "business": os.getenv("STRIPE_PRICE_BUSINESS", ""),
    }
    price_id = price_ids.get(plan)
    if not price_id:
        return jsonify({"error": f"Invalid plan. Choose: {', '.join(price_ids.keys())}"}), 400

    result = create_subscription_checkout(
        price_id=price_id,
        email=data.get("email", ""),
        existing_key=data.get("existing_key", ""),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Stripe webhook endpoint. Configure in Stripe Dashboard > Webhooks."""
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    result, status = handle_webhook(payload, sig)
    return jsonify(result), status


# ── Your API Endpoints ───────────────────────────────────────────────────────
# Add your business logic here. Use @require_api_key(cost=X) to protect routes.


@app.route("/api/example", methods=["POST"])
@require_api_key(cost=0.01)
def api_example():
    """Example paid endpoint. Costs $0.01 per call.
    Replace this with your actual API logic."""
    data = request.get_json() or {}
    return jsonify({
        "result": "Hello from your SaaS API!",
        "input": data,
        "cost": 0.01,
        "key": request.api_key[:12] + "...",
    })


# ── Admin Routes ─────────────────────────────────────────────────────────────


@app.route("/admin/keys", methods=["GET"])
@require_admin
def admin_list_keys():
    """List all API keys with usage stats."""
    from auth import _conn
    with _conn() as c:
        rows = c.execute(
            "SELECT key, label, balance_usd, total_spent, call_count, "
            "subscription_tier, is_active, created_at, last_used_at "
            "FROM api_keys ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return jsonify({"keys": [dict(r) for r in rows]})


@app.route("/admin/keys/<key>/topup", methods=["POST"])
@require_admin
def admin_topup(key):
    """Admin: add balance to any key. Body: {"amount": 10.0}"""
    data = request.get_json() or {}
    amount = float(data.get("amount", 0))
    if amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400
    result = topup_key(key, amount)
    return jsonify(result)


@app.route("/admin/keys/<key>/revoke", methods=["POST"])
@require_admin
def admin_revoke(key):
    """Admin: deactivate any key."""
    revoke_key(key)
    return jsonify({"revoked": True, "key": key})


@app.route("/admin/stats", methods=["GET"])
@require_admin
def admin_stats():
    """Dashboard stats: total keys, revenue, active users."""
    from auth import _conn
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) as n FROM api_keys").fetchone()["n"]
        active = c.execute("SELECT COUNT(*) as n FROM api_keys WHERE is_active = 1").fetchone()["n"]
        revenue = c.execute("SELECT COALESCE(SUM(total_spent), 0) as n FROM api_keys").fetchone()["n"]
        today_spend = c.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) as n FROM daily_spend WHERE date = date('now')"
        ).fetchone()["n"]
    return jsonify({
        "total_keys": total,
        "active_keys": active,
        "total_revenue_usd": round(revenue, 2),
        "today_spend_usd": round(today_spend, 2),
    })


# ── Startup ──────────────────────────────────────────────────────────────────


def create_app():
    """Application factory for gunicorn or testing."""
    init_db()
    logger.info("%s started on %s", APP_NAME, BASE_URL)
    return app


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 5000))
    logger.info("Starting %s on port %d", APP_NAME, port)
    app.run(host="0.0.0.0", port=port, debug=True)
