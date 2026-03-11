"""Authentication, API-key management, credits, and Stripe checkout routes."""

import os
import re
import subprocess
import threading
from datetime import datetime

import stripe as _stripe
from flask import Blueprint, request, jsonify, render_template

from api_keys import generate_key, topup_key, get_key_status
from helpers import log_payment, require_admin, check_identity_rate_limit
from funnel_tracker import log_event as funnel_log_event
from referral import record_conversion

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

BASE_URL = os.getenv("BASE_URL", "https://api.aipaygen.com")

if STRIPE_SECRET_KEY:
    _stripe.api_key = STRIPE_SECRET_KEY

_NOTIFY_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "checkout_alerts.log")


def _notify_checkout(amount, action, api_key):
    """Log checkout and broadcast wall notification."""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = f"[{ts}] CHECKOUT ${amount} ({action}) key={api_key[:12]}..."
    try:
        with open(_NOTIFY_LOG, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    # Broadcast to all terminals (non-blocking)
    def _wall():
        try:
            wall_msg = f"AiPayGen: ${amount} checkout ({action})"
            subprocess.run(["wall", wall_msg], timeout=3, capture_output=True)
        except Exception:
            pass
    threading.Thread(target=_wall, daemon=True).start()

auth_bp = Blueprint("auth", __name__)


# ── Auth / Key Management ─────────────────────────────────────────────────────

@auth_bp.route("/auth/generate-key", methods=["POST"])
def auth_generate_key():
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr)
    if not check_identity_rate_limit(ip):
        return jsonify({"error": "rate_limited", "message": "Too many key generation requests. Max 10/min."}), 429
    data = request.get_json() or {}
    label = data.get("label", "")
    key_data = generate_key(initial_balance=0.0, label=label)
    return jsonify({
        "key": key_data["key"],
        "balance_usd": key_data["balance_usd"],
        "label": key_data["label"],
        "created_at": key_data["created_at"],
        "usage": "Add 'Authorization: Bearer <key>' to your requests. Topup via POST /auth/topup.",
        "_meta": {"free": True},
    })


@auth_bp.route("/auth/topup", methods=["POST"])
@require_admin
def auth_topup():
    data = request.get_json() or {}
    key = data.get("key", "")
    amount = float(data.get("amount_usd", 0))
    if not key or amount <= 0:
        return jsonify({"error": "key and amount_usd required"}), 400
    result = topup_key(key, amount)
    return jsonify(result)


@auth_bp.route("/auth/status", methods=["GET", "POST"])
def auth_status():
    key = request.args.get("key") or (request.get_json() or {}).get("key", "")
    if not key:
        return jsonify({"error": "key required"}), 400
    status = get_key_status(key)
    if not status:
        return jsonify({"error": "key_not_found"}), 404
    return jsonify(status)


@auth_bp.route("/credits/buy", methods=["POST", "GET"])
def buy_credits():
    """Buy API credits. POST with x402 payment or GET for Stripe checkout link."""
    if request.method == "GET":
        return jsonify({
            "how_to_buy": {
                "stripe": {
                    "description": "Pay with credit card via Stripe checkout",
                    "url": "https://api.aipaygen.com/buy-credits",
                    "api": "POST /stripe/create-checkout with {\"amount_usd\": 5.0}",
                },
                "x402": {
                    "description": "Pay with USDC on this endpoint (x402 protected)",
                    "method": "POST /credits/buy with {\"amount_usd\": 5.0} and X-Payment header",
                },
            },
        })
    # POST — requires x402 payment or API key auth (handled by WSGI middleware)
    data = request.get_json() or {}
    amount = data.get("amount_usd", 5.0)
    label = data.get("label", "credit-pack")
    # Only generate key if caller already paid (API key bypass or x402)
    if not request.environ.get("X_APIKEY_BYPASS") and not request.headers.get("X-Payment"):
        # Return Stripe checkout URL instead of free key
        if STRIPE_SECRET_KEY:
            try:
                session = _stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": int(amount * 100),
                            "product_data": {"name": f"AiPayGen API Credits (${amount})"},
                        },
                        "quantity": 1,
                    }],
                    mode="payment",
                    success_url=f"{BASE_URL}/buy-credits/success?session_id={{CHECKOUT_SESSION_ID}}",
                    cancel_url=f"{BASE_URL}/buy-credits",
                    metadata={"amount_usd": str(amount), "label": label},
                )
                _ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
                if _ip not in ("127.0.0.1", "::1"):
                    funnel_log_event("checkout_started", endpoint="/credits/buy",
                                     ip=_ip, metadata=f'{{"amount_usd": {amount}}}')
                return jsonify({"checkout_url": session.url, "amount_usd": amount})
            except Exception as e:
                return jsonify({"error": "stripe_error", "message": str(e)}), 500
        # No Stripe — fall through to x402
        return jsonify({
            "error": "payment_required",
            "message": "Payment required to generate API key.",
            "options": {
                "stripe": "POST /stripe/create-checkout",
                "x402": "Retry with X-Payment header",
            },
        }), 402
    key_data = generate_key(initial_balance=amount, label=label)
    try:
        funnel_log_event("credits_bought", endpoint="/credits/buy",
                         ip=request.headers.get("CF-Connecting-IP", request.remote_addr or ""),
                         metadata=f'{{"amount_usd": {amount}}}')
        funnel_log_event("key_generated", endpoint="/credits/buy",
                         ip=request.headers.get("CF-Connecting-IP", request.remote_addr or ""))
    except Exception:
        pass
    return jsonify({
        "key": key_data["key"],
        "balance_usd": amount,
        "label": label,
        "pricing": "Use 'X-Pricing: metered' header for token-based billing",
    })


# ── Stripe Checkout & Webhook ─────────────────────────────────────────────────



@auth_bp.route("/webhooks/register", methods=["POST"])
def register_user_webhook():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer apk_"):
        return jsonify({"error": "API key required"}), 401
    api_key = auth[7:]
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    events = data.get("events", [])
    if not url or not events:
        return jsonify({"error": "url and events required"}), 400
    from webhook_dispatch import register_webhook
    wh_id = register_webhook(api_key, url, events)
    if wh_id is None:
        return jsonify({"error": "Invalid URL — must be HTTPS"}), 400
    return jsonify({"webhook_id": wh_id, "url": url, "events": events})


@auth_bp.route("/webhooks", methods=["GET"])
def list_user_webhooks():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer apk_"):
        return jsonify({"error": "API key required"}), 401
    from webhook_dispatch import list_webhooks
    return jsonify({"webhooks": list_webhooks(auth[7:])})


@auth_bp.route("/webhooks/<int:webhook_id>", methods=["DELETE"])
def delete_user_webhook(webhook_id):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer apk_"):
        return jsonify({"error": "API key required"}), 401
    from webhook_dispatch import delete_webhook
    if delete_webhook(webhook_id, auth[7:]):
        return jsonify({"deleted": True})
    return jsonify({"error": "Not found or not owned by this key"}), 404


@auth_bp.route("/buy-credits", methods=["GET"])
def buy_credits_page():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured. Set STRIPE_SECRET_KEY in .env"}), 503
    return render_template("buy_credits.html"), 200, {"Content-Type": "text/html"}


@auth_bp.route("/stripe/create-checkout", methods=["POST"])
def stripe_create_checkout():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured"}), 503
    data = request.get_json() or {}
    amount = int(data.get("amount", 20))
    if amount not in (1, 5, 10, 15, 20, 25, 50):
        return jsonify({"error": "amount must be 1, 5, 10, 15, 20, 25, or 50"}), 400
    label = str(data.get("label", ""))[:60]
    existing_key = str(data.get("existing_key", "")).strip()

    # Validate existing key for top-up, but do NOT generate new keys yet.
    # New keys are created in the webhook after payment is confirmed.
    if existing_key and existing_key.startswith("apk_"):
        status = get_key_status(existing_key)
        if not status:
            return jsonify({"error": "key not found"}), 404
        action = "topup"
    else:
        existing_key = ""
        action = "new"

    try:
        session = _stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"AiPayGen API Credits — ${amount}",
                        "description": f"Prepaid credits for api.aipaygen.com. ~{amount * 100} API calls.",
                    },
                    "unit_amount": amount * 100,  # cents
                },
                "quantity": 1,
            }],
            mode="payment",
            client_reference_id=existing_key or "new",
            metadata={"amount": str(amount), "action": action, "label": label,
                       **({"api_key": existing_key} if existing_key else {})},
            success_url=f"{BASE_URL}/buy-credits/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/buy-credits",
        )
        ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
        if ip not in ("127.0.0.1", "::1"):
            funnel_log_event("checkout_started", endpoint="/stripe/create-checkout",
                             ip=ip, metadata=f'{{"amount_usd": {amount}}}')
        return jsonify({"url": session.url, "session_id": session.id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "webhook secret not set"}), 503
    try:
        event = _stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except _stripe.error.SignatureVerificationError:
        return jsonify({"error": "invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {})
        amount = float(meta.get("amount", 0))
        action = meta.get("action", "new")
        label = meta.get("label", "credit-pack")
        api_key = meta.get("api_key", "")

        if amount > 0:
            if action == "topup" and api_key and api_key.startswith("apk_"):
                topup_key(api_key, amount)
            else:
                # Generate new key with full balance on confirmed payment
                new_key = generate_key(initial_balance=amount, label=label)
                api_key = new_key["key"]
                # Store key in session metadata so success page can retrieve it
                try:
                    _stripe.checkout.Session.modify(session["id"], metadata={**meta, "api_key": api_key})
                except Exception:
                    pass

            log_payment("/stripe/topup", amount, session.get("customer_details", {}).get("email", "stripe"))
            _notify_checkout(amount, "PAID", api_key)

            # Send API key email and link to account
            customer_email = session.get("customer_details", {}).get("email", "")
            if customer_email and api_key:
                try:
                    from email_service import send_api_key_email
                    from accounts import create_or_get_account, link_key_to_account
                    bal = float(meta.get("amount", 0))
                    send_api_key_email(customer_email, api_key, bal)
                    acct = create_or_get_account(customer_email)
                    link_key_to_account(acct["id"], api_key)
                except Exception:
                    pass

            # Credit referral commission if ?ref= was passed during checkout
            ref_agent = meta.get("ref_agent", "")
            if ref_agent:
                try:
                    record_conversion(ref_agent, "stripe_purchase", amount)
                except Exception:
                    pass

    return jsonify({"received": True})


@auth_bp.route("/auth/key-status", methods=["GET"])
def key_status():
    session_id = request.args.get("session_id", "")
    if not session_id:
        return jsonify({"ready": False})
    try:
        session = _stripe.checkout.Session.retrieve(session_id)
        key = session.metadata.get("api_key")
        if key:
            return jsonify({"ready": True, "api_key": key, "balance": session.metadata.get("balance_usd", session.metadata.get("amount", "0"))})
        return jsonify({"ready": False})
    except Exception:
        return jsonify({"ready": False})


@auth_bp.route("/buy-credits/success", methods=["GET"])
def buy_credits_success():
    return render_template("buy_credits_success.html"), 200, {"Content-Type": "text/html"}
