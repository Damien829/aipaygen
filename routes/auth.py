"""Authentication, API-key management, credits, and Stripe checkout routes."""

import json
import os
import re
import subprocess
import threading
import time as _time
from datetime import datetime

import stripe as _stripe
from flask import Blueprint, request, jsonify, render_template, make_response

from api_keys import generate_key, topup_key, get_key_status, get_key_by_referral_code
from helpers import log_payment, require_admin, require_api_key, check_identity_rate_limit
from funnel_tracker import log_event as funnel_log_event
import logging

from referral import record_conversion
from notifications import create_notification

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

BASE_URL = os.getenv("BASE_URL", "https://api.aipaygen.com")

if STRIPE_SECRET_KEY:
    _stripe.api_key = STRIPE_SECRET_KEY

_NOTIFY_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "checkout_alerts.log")

# In-memory mapping of Stripe session_id -> api_key for race-condition-free key retrieval.
# Written AFTER DB insert but BEFORE Stripe metadata update, so /auth/key-status
# can always find the key even if Stripe metadata update hasn't completed yet.
# Bounded: entries older than 24h are evicted to prevent memory growth.
_session_key_map = {}
_session_key_ts = {}  # track insertion time
_SESSION_KEY_TTL = 86400  # 24 hours


def _cleanup_session_keys():
    now = _time.time()
    stale = [k for k, ts in _session_key_ts.items() if now - ts > _SESSION_KEY_TTL]
    for k in stale:
        _session_key_map.pop(k, None)
        _session_key_ts.pop(k, None)


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
    source = data.get("source", request.cookies.get("aipaygen_ref", "api-direct"))
    email = (data.get("email") or "").strip().lower()
    ref_code = data.get("ref", "") or request.args.get("ref", "") or request.cookies.get("aipaygen_ref", "")
    # MCP tool users get $0.25 trial credits
    trial_balance = 0.25 if source == "mcp-tool" else 0.0
    key_data = generate_key(initial_balance=trial_balance, label=label, source=source)

    # ── Referral bonus ────────────────────────────────────────────────────
    referral_applied = False
    if ref_code:
        referrer = get_key_by_referral_code(ref_code)
        if referrer and referrer["key"] != key_data["key"]:
            # Credit both parties $0.10
            topup_key(referrer["key"], 0.10)
            topup_key(key_data["key"], 0.10)
            key_data["balance_usd"] = round(key_data["balance_usd"] + 0.10, 2)
            referral_applied = True
            try:
                funnel_log_event("referral_signup", ip=ip,
                                 metadata=json.dumps({"ref_code": ref_code, "referrer_key": referrer["key"][:12]}))
            except Exception:
                pass

    if email:
        from accounts import create_or_get_account, link_key_to_account
        acct = create_or_get_account(email)
        link_key_to_account(acct["id"], key_data["key"])
        try:
            funnel_log_event("email_captured", ip=ip,
                             metadata=json.dumps({"source": source}))
        except Exception:
            pass
    api_key = key_data["key"]
    try:
        funnel_log_event("key_generated", endpoint="/auth/generate-key",
                         ip=ip, metadata=json.dumps({"source": source}))
    except Exception:
        pass
    resp_data = {
        "key": api_key,
        "balance_usd": key_data["balance_usd"],
        "label": key_data["label"],
        "created_at": key_data["created_at"],
        "source": key_data.get("source", source),
        "referral_code": key_data.get("referral_code", ""),
        "referral_link": f"https://aipaygen.com/buy-credits?ref={key_data.get('referral_code', '')}",
        "usage": "Add 'Authorization: Bearer <key>' to your requests. Topup via POST /auth/topup.",
        "_meta": {"free": True},
        "quickstart": {
            "curl_example": f"curl -X POST -H 'Authorization: Bearer {api_key}' {BASE_URL}/sentiment -d '{{\"text\": \"hello world\"}}'",
            "mcp_install": "pip install aipaygen-mcp && claude mcp add aipaygen -- aipaygen-mcp",
            "docs": f"{BASE_URL}/docs",
            "free_calls": 10,
            "note": "You get 10 free calls/day. No payment needed to start.",
        },
    }
    if referral_applied:
        resp_data["referral_bonus"] = "$0.10 credited to you and your referrer!"
    # ── Notifications ──────────────────────────────────────────────────────
    bal = key_data["balance_usd"]
    create_notification(api_key, "key_generated",
                        f"Welcome! You have ${bal:.2f} trial credits. Visit /docs to get started.")
    if referral_applied:
        create_notification(api_key, "referral_bonus", "You earned $0.10 from a referral!")
        if ref_code:
            referrer_obj = get_key_by_referral_code(ref_code)
            if referrer_obj:
                create_notification(referrer_obj["key"], "referral_bonus",
                                    "You earned $0.10 from a referral!")
    return jsonify(resp_data)


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
@require_api_key
def auth_status():
    key = request.args.get("key") or (request.get_json() or {}).get("key", "")
    if not key:
        return jsonify({"error": "key required"}), 400
    # Only allow checking your own key
    bearer = (request.headers.get("Authorization", "")[7:]
              if request.headers.get("Authorization", "").startswith("Bearer ") else "")
    if bearer and key != bearer:
        return jsonify({"error": "unauthorized", "message": "Can only check your own key status"}), 403
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
                logger.error("Stripe checkout session creation failed: %s", e)
                return jsonify({"error": "stripe_error", "message": "Payment processing failed"}), 500
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
    if not url.startswith("https://"):
        return jsonify({"error": "Invalid URL — must be HTTPS"}), 400
    from webhook_dispatch import register_webhook
    wh_id = register_webhook(api_key, url, events)
    if wh_id is None:
        return jsonify({"error": "Failed to register webhook"}), 400
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


@auth_bp.route("/auth/notifications", methods=["GET"])
@require_api_key
def auth_notifications():
    """Return unread notifications for the authenticated API key, then mark them read."""
    bearer = (request.headers.get("Authorization", "")[7:]
              if request.headers.get("Authorization", "").startswith("Bearer ") else "")
    if not bearer:
        return jsonify({"error": "API key required"}), 401
    from notifications import get_unread
    notes = get_unread(bearer, limit=20)
    return jsonify({"notifications": notes, "count": len(notes)})


@auth_bp.route("/buy-credits", methods=["GET"])
def buy_credits_page():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured. Set STRIPE_SECRET_KEY in .env"}), 503
    resp = make_response(render_template("buy_credits.html"))
    resp.headers["Content-Type"] = "text/html"
    ref = request.args.get("ref", "")
    if ref:
        resp.set_cookie("aipaygen_ref", ref, max_age=30*86400, secure=True, httponly=True, samesite="Lax")
    return resp


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
    email = str(data.get("email", "")).strip().lower()[:120]

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
                       "ref_source": request.cookies.get("aipaygen_ref", "direct"),
                       **({"api_key": existing_key} if existing_key else {}),
                       **({"customer_email": email} if email else {})},
            success_url=f"{BASE_URL}/buy-credits/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/buy-credits",
        )
        ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
        if ip not in ("127.0.0.1", "::1"):
            funnel_log_event("checkout_started", endpoint="/stripe/create-checkout",
                             ip=ip, metadata=f'{{"amount_usd": {amount}}}')
        return jsonify({"url": session.url, "session_id": session.id})
    except Exception as e:
        logger.error("Stripe checkout creation failed: %s", e)
        return jsonify({"error": "Payment processing failed"}), 500


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
                # Generate new key with full balance on confirmed payment.
                # DB write happens inside generate_key() FIRST, then we store
                # in the in-memory map, then update Stripe metadata last.
                # This ordering prevents the race where /auth/key-status polls
                # before the Stripe metadata update completes.
                ref_source = meta.get("ref_source", "stripe")
                new_key = generate_key(initial_balance=amount, label=label, source=ref_source)
                api_key = new_key["key"]
                _cleanup_session_keys()
                _session_key_map[session["id"]] = api_key
                _session_key_ts[session["id"]] = _time.time()

                # Also store in Stripe session metadata for the success page
                try:
                    _stripe.checkout.Session.modify(session["id"], metadata={**meta, "api_key": api_key})
                except Exception:
                    pass

            log_payment("/stripe/topup", amount, session.get("customer_details", {}).get("email", "stripe"))
            _notify_checkout(amount, "PAID", api_key)
            # In-app notification for payment
            if api_key:
                status_info = get_key_status(api_key)
                new_bal = status_info["balance_usd"] if status_info else amount
                create_notification(api_key, "payment_received",
                                    f"Payment of ${amount:.2f} received. Balance: ${new_bal:.2f}")

            # Send API key email and link to account
            customer_email = (session.get("customer_details", {}).get("email", "")
                              or meta.get("customer_email", ""))
            if customer_email and api_key:
                try:
                    from email_service import send_api_key_email, send_welcome_email
                    from accounts import create_or_get_account, link_key_to_account
                    bal = float(meta.get("amount", 0))
                    send_api_key_email(customer_email, api_key, bal)
                    send_welcome_email(customer_email, api_key)
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
    # Check in-memory map first (populated before Stripe metadata update)
    key = _session_key_map.get(session_id)
    if key:
        status = get_key_status(key)
        return jsonify({"ready": True, "api_key": key, "balance": str(status.get("balance_usd", "0") if status else "0")})
    # Fall back to Stripe metadata
    try:
        session = _stripe.checkout.Session.retrieve(session_id)
        key = session.metadata.get("api_key")
        if key:
            return jsonify({"ready": True, "api_key": key, "balance": session.metadata.get("balance_usd", session.metadata.get("amount", "0"))})
        return jsonify({"ready": False})
    except Exception:
        return jsonify({"ready": False})


@auth_bp.route("/auth/usage-digest", methods=["POST"])
@require_api_key
def auth_usage_digest():
    """Send a weekly usage digest email for the authenticated API key."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    bearer = (request.headers.get("Authorization", "")[7:]
              if request.headers.get("Authorization", "").startswith("Bearer ") else "")
    if not bearer:
        return jsonify({"error": "API key required"}), 401
    # If no email provided, try to look it up from accounts
    if not email:
        try:
            import sqlite3
            accounts_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), "accounts.db")
            conn = sqlite3.connect(accounts_db)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT a.email FROM accounts a JOIN account_keys ak ON a.id = ak.account_id "
                "WHERE ak.api_key = ?", (bearer,)
            ).fetchone()
            conn.close()
            if row:
                email = row["email"]
        except Exception:
            pass
    if not email:
        return jsonify({"error": "email required — provide in body or link your key to an account"}), 400
    from email_service import send_usage_digest
    ok = send_usage_digest(email, bearer)
    if ok:
        return jsonify({"sent": True, "email": email})
    return jsonify({"error": "Failed to send digest"}), 500


@auth_bp.route("/buy-credits/success", methods=["GET"])
def buy_credits_success():
    return render_template("buy_credits_success.html"), 200, {"Content-Type": "text/html"}
