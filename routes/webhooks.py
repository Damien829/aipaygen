"""Full webhook infrastructure: subscriptions, deliveries, HMAC signing, retry queue."""
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import requests as _requests
from flask import Blueprint, request, jsonify, render_template

from helpers import require_api_key

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__)

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "webhooks.db")

SUPPORTED_EVENTS = [
    "trade.opened",
    "trade.closed",
    "strategy.activated",
    "strategy.paused",
    "a2a.rfq.created",
    "a2a.rfq.accepted",
    "a2a.transaction.completed",
    "marketplace.purchase",
    "marketplace.review",
    "balance.low",
    "balance.deposit",
]

MAX_RETRIES = 3
DELIVERY_TIMEOUT = 10  # seconds


# ── DB helpers ──────────────────────────────────────────────────────────

@contextmanager
def _conn():
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _init_webhooks_db():
    """Create webhook tables if they don't exist."""
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS webhook_subscriptions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            url TEXT NOT NULL,
            events TEXT NOT NULL DEFAULT '[]',
            secret TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_delivery_at TEXT,
            failure_count INTEGER NOT NULL DEFAULT 0
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            response_code INTEGER,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            FOREIGN KEY (subscription_id) REFERENCES webhook_subscriptions(id)
        )""")

        c.execute("CREATE INDEX IF NOT EXISTS idx_ws_user ON webhook_subscriptions(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ws_active ON webhook_subscriptions(active)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_wd_sub ON webhook_deliveries(subscription_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_wd_status ON webhook_deliveries(status)")


# Initialize on import
_init_webhooks_db()


# ── Signing ─────────────────────────────────────────────────────────────

def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for a payload."""
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


# ── Core functions ──────────────────────────────────────────────────────

def fire_event(event_type: str, payload: dict):
    """Find all active subscriptions for this event type and queue deliveries."""
    now = datetime.now(timezone.utc).isoformat()
    queued = 0
    with _conn() as c:
        rows = c.execute(
            "SELECT id, events FROM webhook_subscriptions WHERE active = 1"
        ).fetchall()
        for row in rows:
            try:
                events = json.loads(row["events"])
            except (json.JSONDecodeError, TypeError):
                events = []
            if event_type in events or "*" in events:
                delivery_id = str(uuid.uuid4())
                c.execute(
                    "INSERT INTO webhook_deliveries (id, subscription_id, event_type, payload, status, attempts, created_at) "
                    "VALUES (?, ?, ?, ?, 'pending', 0, ?)",
                    (delivery_id, row["id"], event_type, json.dumps(payload), now),
                )
                queued += 1
    # Kick off async delivery
    if queued > 0:
        threading.Thread(target=process_webhook_queue, daemon=True).start()
    return queued


def deliver_webhook(delivery_id: str) -> bool:
    """POST payload to the subscription URL with HMAC signature. Retry up to 3 times with exponential backoff."""
    with _conn() as c:
        row = c.execute(
            "SELECT d.id, d.subscription_id, d.event_type, d.payload, d.attempts, "
            "s.url, s.secret, s.id as sub_id "
            "FROM webhook_deliveries d "
            "JOIN webhook_subscriptions s ON d.subscription_id = s.id "
            "WHERE d.id = ?",
            (delivery_id,),
        ).fetchone()
    if not row:
        return False

    payload_bytes = row["payload"].encode()
    signature = _sign_payload(payload_bytes, row["secret"])
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": f"sha256={signature}",
        "X-Webhook-Event": row["event_type"],
        "X-Webhook-Delivery": delivery_id,
        "User-Agent": "AiPayGen-Webhooks/1.0",
    }

    attempts = row["attempts"]
    success = False

    for attempt in range(attempts, MAX_RETRIES):
        wait = 2 ** attempt  # 1s, 2s, 4s
        if attempt > 0:
            time.sleep(wait)

        try:
            resp = _requests.post(
                row["url"], data=payload_bytes, headers=headers, timeout=DELIVERY_TIMEOUT
            )
            now = datetime.now(timezone.utc).isoformat()
            with _conn() as c:
                c.execute(
                    "UPDATE webhook_deliveries SET attempts = ?, response_code = ? WHERE id = ?",
                    (attempt + 1, resp.status_code, delivery_id),
                )
                if 200 <= resp.status_code < 300:
                    c.execute(
                        "UPDATE webhook_deliveries SET status = 'delivered', delivered_at = ? WHERE id = ?",
                        (now, delivery_id),
                    )
                    c.execute(
                        "UPDATE webhook_subscriptions SET last_delivery_at = ?, failure_count = 0 WHERE id = ?",
                        (now, row["sub_id"]),
                    )
                    success = True
                    break
        except Exception as exc:
            logger.warning("Webhook delivery %s attempt %d failed: %s", delivery_id, attempt + 1, exc)
            with _conn() as c:
                c.execute(
                    "UPDATE webhook_deliveries SET attempts = ? WHERE id = ?",
                    (attempt + 1, delivery_id),
                )

    if not success:
        with _conn() as c:
            c.execute("UPDATE webhook_deliveries SET status = 'failed' WHERE id = ?", (delivery_id,))
            c.execute(
                "UPDATE webhook_subscriptions SET failure_count = failure_count + 1 WHERE id = ?",
                (row["sub_id"],),
            )
            # Auto-disable after 10 consecutive failures
            c.execute(
                "UPDATE webhook_subscriptions SET active = 0 WHERE id = ? AND failure_count >= 10",
                (row["sub_id"],),
            )

    return success


def process_webhook_queue():
    """Process all pending deliveries. Suitable for scheduler or background thread."""
    with _conn() as c:
        pending = c.execute(
            "SELECT id FROM webhook_deliveries WHERE status = 'pending' AND attempts < ? ORDER BY created_at",
            (MAX_RETRIES,),
        ).fetchall()
    for row in pending:
        try:
            deliver_webhook(row["id"])
        except Exception as exc:
            logger.error("Error processing delivery %s: %s", row["id"], exc)


# ── Routes ──────────────────────────────────────────────────────────────

@webhooks_bp.route("/webhooks/subscribe", methods=["POST"])
@require_api_key
def webhook_subscribe():
    """Register a webhook URL for specific events."""
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    events = data.get("events", [])

    if not url:
        return jsonify({"error": "url is required"}), 400
    if not url.startswith("https://"):
        return jsonify({"error": "url must use HTTPS"}), 400
    if not events or not isinstance(events, list):
        return jsonify({"error": "events must be a non-empty list"}), 400

    invalid = [e for e in events if e not in SUPPORTED_EVENTS and e != "*"]
    if invalid:
        return jsonify({"error": f"unsupported events: {invalid}", "supported": SUPPORTED_EVENTS}), 400

    sub_id = str(uuid.uuid4())
    secret = secrets.token_hex(32)
    now = datetime.now(timezone.utc).isoformat()

    with _conn() as c:
        # Limit subscriptions per user
        count = c.execute(
            "SELECT COUNT(*) FROM webhook_subscriptions WHERE user_id = ? AND active = 1",
            (request.api_key,),
        ).fetchone()[0]
        if count >= 20:
            return jsonify({"error": "maximum 20 active subscriptions"}), 429

        c.execute(
            "INSERT INTO webhook_subscriptions (id, user_id, url, events, secret, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (sub_id, request.api_key, url, json.dumps(events), secret, now),
        )

    return jsonify({
        "id": sub_id,
        "url": url,
        "events": events,
        "secret": secret,
        "active": True,
        "created_at": now,
        "message": "Store the secret — it won't be shown again.",
    }), 201


@webhooks_bp.route("/webhooks", methods=["GET"])
@require_api_key
def webhook_list():
    """List user's webhook subscriptions."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, url, events, active, created_at, last_delivery_at, failure_count "
            "FROM webhook_subscriptions WHERE user_id = ? ORDER BY created_at DESC",
            (request.api_key,),
        ).fetchall()

    subs = []
    for r in rows:
        subs.append({
            "id": r["id"],
            "url": r["url"],
            "events": json.loads(r["events"]),
            "active": bool(r["active"]),
            "created_at": r["created_at"],
            "last_delivery_at": r["last_delivery_at"],
            "failure_count": r["failure_count"],
        })
    return jsonify({"subscriptions": subs, "count": len(subs)})


@webhooks_bp.route("/webhooks/<sub_id>", methods=["DELETE"])
@require_api_key
def webhook_delete(sub_id):
    """Remove a webhook subscription."""
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM webhook_subscriptions WHERE id = ? AND user_id = ?",
            (sub_id, request.api_key),
        ).fetchone()
        if not row:
            return jsonify({"error": "subscription not found"}), 404
        c.execute("DELETE FROM webhook_subscriptions WHERE id = ?", (sub_id,))
        c.execute("DELETE FROM webhook_deliveries WHERE subscription_id = ?", (sub_id,))
    return jsonify({"deleted": sub_id})


@webhooks_bp.route("/webhooks/<sub_id>/deliveries", methods=["GET"])
@require_api_key
def webhook_deliveries(sub_id):
    """View delivery history for a subscription."""
    limit = min(int(request.args.get("limit", 50)), 200)

    with _conn() as c:
        # Verify ownership
        owner = c.execute(
            "SELECT id FROM webhook_subscriptions WHERE id = ? AND user_id = ?",
            (sub_id, request.api_key),
        ).fetchone()
        if not owner:
            return jsonify({"error": "subscription not found"}), 404

        rows = c.execute(
            "SELECT id, event_type, payload, status, response_code, attempts, created_at, delivered_at "
            "FROM webhook_deliveries WHERE subscription_id = ? ORDER BY created_at DESC LIMIT ?",
            (sub_id, limit),
        ).fetchall()

    deliveries = []
    for r in rows:
        deliveries.append({
            "id": r["id"],
            "event_type": r["event_type"],
            "payload": json.loads(r["payload"]),
            "status": r["status"],
            "response_code": r["response_code"],
            "attempts": r["attempts"],
            "created_at": r["created_at"],
            "delivered_at": r["delivered_at"],
        })
    return jsonify({"deliveries": deliveries, "count": len(deliveries)})


@webhooks_bp.route("/webhooks/test/<sub_id>", methods=["POST"])
@require_api_key
def webhook_test(sub_id):
    """Send a test event to a specific subscription."""
    with _conn() as c:
        row = c.execute(
            "SELECT id, events FROM webhook_subscriptions WHERE id = ? AND user_id = ? AND active = 1",
            (sub_id, request.api_key),
        ).fetchone()
        if not row:
            return jsonify({"error": "subscription not found or inactive"}), 404

    events = json.loads(row["events"])
    test_event = events[0] if events and events[0] != "*" else "trade.opened"

    test_payload = {
        "event": test_event,
        "test": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {"message": "This is a test webhook delivery from AiPayGen."},
    }

    now = datetime.now(timezone.utc).isoformat()
    delivery_id = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO webhook_deliveries (id, subscription_id, event_type, payload, status, attempts, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', 0, ?)",
            (delivery_id, sub_id, test_event, json.dumps(test_payload), now),
        )

    # Deliver synchronously for test so caller gets result
    success = deliver_webhook(delivery_id)

    with _conn() as c:
        d = c.execute(
            "SELECT status, response_code, attempts FROM webhook_deliveries WHERE id = ?",
            (delivery_id,),
        ).fetchone()

    return jsonify({
        "delivery_id": delivery_id,
        "event": test_event,
        "success": success,
        "status": d["status"] if d else "unknown",
        "response_code": d["response_code"] if d else None,
        "attempts": d["attempts"] if d else 0,
    })


# ── Legacy UI route ─────────────────────────────────────────────────────

@webhooks_bp.route("/webhooks/test-page")
def webhook_test_page():
    """Webhook testing UI."""
    try:
        from routes.meta import NAV_HTML, FOOTER_HTML
        return render_template("webhook_test.html", nav=NAV_HTML, footer=FOOTER_HTML)
    except Exception:
        return jsonify({"error": "template not available"}), 404


# ── Supported events endpoint ──────────────────────────────────────────

@webhooks_bp.route("/webhooks/events", methods=["GET"])
def webhook_events():
    """List all supported webhook event types."""
    return jsonify({"events": SUPPORTED_EVENTS})
