"""Authentication, API-key management, credits, and Stripe checkout routes."""

import os
import re

import stripe as _stripe
from flask import Blueprint, request, jsonify

from api_keys import generate_key, topup_key, get_key_status
from helpers import log_payment
from funnel_tracker import log_event as funnel_log_event
from referral import record_conversion

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

BASE_URL = os.getenv("BASE_URL", "https://api.aipaygen.com")

if STRIPE_SECRET_KEY:
    _stripe.api_key = STRIPE_SECRET_KEY

auth_bp = Blueprint("auth", __name__)


# ── Auth / Key Management ─────────────────────────────────────────────────────

@auth_bp.route("/auth/generate-key", methods=["POST"])
def auth_generate_key():
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
                funnel_log_event("checkout_started", endpoint="/credits/buy",
                                 ip=request.headers.get("CF-Connecting-IP", request.remote_addr or ""),
                                 metadata=f'{{"amount_usd": {amount}}}')
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

_BUY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Buy AiPayGen Credits — 88 AI Tools, One Key</title>
<meta name="description" content="Get instant access to 88 AI tools: research, write, code, translate, analyze, scrape, and more. Pay once, no subscriptions.">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 32px 16px; }
  a { color: #818cf8; }
  .wrapper { max-width: 600px; width: 100%; }

  /* Try it banner */
  .try-banner { background: linear-gradient(135deg, #1a1a3e, #0d1a2d); border: 1px solid #2d2d5e; border-radius: 12px; padding: 16px 20px; margin-bottom: 20px; display: flex; align-items: center; gap: 12px; }
  .try-banner .icon { font-size: 1.4rem; }
  .try-banner .text { flex: 1; font-size: 0.85rem; color: #a0a0c0; }
  .try-banner .text strong { color: #e0e0ff; }
  .try-banner a { background: #6366f1; color: #fff; text-decoration: none; padding: 8px 16px; border-radius: 8px; font-size: 0.85rem; font-weight: 600; white-space: nowrap; }

  /* Main card */
  .card { background: #141414; border: 1px solid #2a2a2a; border-radius: 16px; padding: 36px; }
  h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }
  .sub { color: #888; font-size: 0.88rem; margin-bottom: 28px; }
  .plans { display: flex; gap: 12px; margin-bottom: 24px; }
  .plan { flex: 1; border: 2px solid #2a2a2a; border-radius: 12px; padding: 18px 12px; cursor: pointer; text-align: center; transition: all 0.15s; position: relative; }
  .plan:hover, .plan.selected { border-color: #6366f1; background: #1a1a2e; }
  .plan .amount { font-size: 1.5rem; font-weight: 800; color: #fff; }
  .plan .credits { font-size: 0.78rem; color: #888; margin-top: 4px; }
  .plan .per-call { font-size: 0.72rem; color: #6366f1; margin-top: 2px; }
  .plan .badge { display: inline-block; background: #6366f1; color: #fff; font-size: 0.68rem; padding: 2px 8px; border-radius: 20px; margin-top: 8px; }
  .plan .badge.green { background: #059669; }

  .field { margin-bottom: 16px; }
  label { display: block; font-size: 0.82rem; color: #888; margin-bottom: 5px; }
  input { width: 100%; background: #1e1e1e; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 14px; color: #e8e8e8; font-size: 0.9rem; outline: none; transition: border-color 0.15s; }
  input:focus { border-color: #6366f1; }
  input::placeholder { color: #555; }
  .btn { width: 100%; background: #6366f1; color: #fff; border: none; border-radius: 10px; padding: 14px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.15s; }
  .btn:hover { background: #4f52d0; }
  .btn:disabled { background: #333; color: #666; cursor: not-allowed; }
  .error { color: #f87171; font-size: 0.85rem; margin-top: 10px; display: none; }

  /* What you get */
  .features { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 24px; padding-top: 24px; border-top: 1px solid #222; }
  .feat { font-size: 0.78rem; color: #888; padding: 6px 0; }
  .feat span { color: #34d399; margin-right: 6px; }

  /* Trust */
  .trust { margin-top: 20px; padding: 14px; background: #1a1a1a; border-radius: 8px; font-size: 0.78rem; color: #666; line-height: 1.6; text-align: center; }
  .trust strong { color: #888; }

  /* How it works */
  .how { margin-top: 20px; padding: 14px; background: #1a1a1a; border-radius: 8px; font-size: 0.8rem; color: #888; line-height: 1.7; }
  .how code { background: #2a2a2a; padding: 1px 5px; border-radius: 4px; color: #a78bfa; font-size: 0.78rem; }
  .how .step { color: #6366f1; font-weight: 700; margin-right: 4px; }

  @media (max-width: 500px) {
    .plans { flex-direction: column; }
    .features { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="wrapper">
  <div class="try-banner">
    <div class="icon">&#9889;</div>
    <div class="text"><strong>Try before you buy</strong> — test any tool free, no key needed</div>
    <a href="/try">Try it free</a>
  </div>

  <div class="card">
    <h1>Get Your API Key</h1>
    <p class="sub">Pay once, call 88 AI tools. No subscriptions, no expiry.</p>

    <div class="plans">
      <div class="plan" data-amount="5" onclick="selectPlan(this)">
        <div class="amount">$5</div>
        <div class="credits">~830 calls</div>
        <div class="per-call">$0.006/call</div>
      </div>
      <div class="plan selected" data-amount="20" onclick="selectPlan(this)">
        <div class="amount">$20</div>
        <div class="credits">~4,000 calls</div>
        <div class="per-call">$0.005/call</div>
        <div class="badge">Popular</div>
      </div>
      <div class="plan" data-amount="50" onclick="selectPlan(this)">
        <div class="amount">$50</div>
        <div class="credits">~12,500 calls</div>
        <div class="per-call">$0.004/call</div>
        <div class="badge green">Best value</div>
      </div>
    </div>

    <div class="field">
      <label>Label (optional)</label>
      <input type="text" id="label" placeholder="e.g. my-agent, production" maxlength="60">
    </div>

    <div class="field">
      <label>Top up existing key (optional)</label>
      <input type="text" id="existing_key" placeholder="apk_xxx — leave blank for a new key">
    </div>

    <button class="btn" id="pay-btn" onclick="checkout()">&#128274; Pay with Card</button>
    <p class="error" id="err"></p>

    <div class="features">
      <div class="feat"><span>&#10003;</span> Research &amp; summarize</div>
      <div class="feat"><span>&#10003;</span> Write &amp; translate</div>
      <div class="feat"><span>&#10003;</span> Code generation</div>
      <div class="feat"><span>&#10003;</span> Web scraping (6 sites)</div>
      <div class="feat"><span>&#10003;</span> Sentiment &amp; analysis</div>
      <div class="feat"><span>&#10003;</span> Agent memory</div>
      <div class="feat"><span>&#10003;</span> 500+ API catalog</div>
      <div class="feat"><span>&#10003;</span> 15 AI models</div>
    </div>

    <div class="trust">
      <strong>88 tools</strong> &middot; <strong>15 AI models</strong> &middot; <strong>500+ APIs</strong> &middot; Published on <strong>PyPI</strong> &amp; <strong>MCP Registry</strong><br>
      Credits never expire &middot; 20% bulk discount at $20+ &middot; Secure checkout via Stripe
    </div>

    <div class="how">
      <span class="step">1.</span> Pay &rarr; get your <code>apk_xxx</code> key instantly<br>
      <span class="step">2.</span> Add <code>Authorization: Bearer apk_xxx</code> to any request<br>
      <span class="step">3.</span> Call any of 88 endpoints &mdash; credits deducted per call
    </div>
  </div>
</div>
<script>
let selectedAmount = 20;
function selectPlan(el) {
  document.querySelectorAll('.plan').forEach(p => p.classList.remove('selected'));
  el.classList.add('selected');
  selectedAmount = parseInt(el.dataset.amount);
}
async function checkout() {
  const btn = document.getElementById('pay-btn');
  const err = document.getElementById('err');
  btn.disabled = true; btn.textContent = 'Redirecting to Stripe...'; err.style.display = 'none';
  try {
    const res = await fetch('/stripe/create-checkout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        amount: selectedAmount,
        label: document.getElementById('label').value.trim(),
        existing_key: document.getElementById('existing_key').value.trim(),
      })
    });
    const data = await res.json();
    if (data.url) { window.location.href = data.url; }
    else { err.textContent = data.error || 'Something went wrong'; err.style.display = 'block'; btn.disabled = false; btn.textContent = '\\u{1F512} Pay with Card'; }
  } catch(e) { err.textContent = 'Network error — please try again'; err.style.display = 'block'; btn.disabled = false; btn.textContent = '\\u{1F512} Pay with Card'; }
}
</script>
</body>
</html>"""

_SUCCESS_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Payment Successful — AiPayGen</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
  .card { background: #141414; border: 1px solid #2a2a2a; border-radius: 16px; padding: 40px; max-width: 520px; width: 100%; text-align: center; }
  .icon { font-size: 3rem; margin-bottom: 16px; }
  h1 { font-size: 1.6rem; margin-bottom: 8px; }
  .sub { color: #888; margin-bottom: 28px; }
  .key-box { background: #1e1e1e; border: 1px solid #2a2a2a; border-radius: 10px; padding: 16px; margin-bottom: 24px; }
  .key-label { font-size: 0.8rem; color: #888; margin-bottom: 6px; }
  .key-val { font-family: monospace; font-size: 0.95rem; color: #a78bfa; word-break: break-all; cursor: pointer; }
  .key-val:hover { color: #c4b5fd; }
  .balance { font-size: 1.1rem; margin-bottom: 24px; }
  .balance span { color: #34d399; font-weight: 700; }
  pre { background: #1a1a1a; border-radius: 8px; padding: 14px; font-size: 0.8rem; color: #888; text-align: left; overflow-x: auto; margin-bottom: 8px; }
  .btn { display: inline-block; background: #6366f1; color: #fff; text-decoration: none; border-radius: 10px; padding: 12px 24px; font-weight: 600; margin-top: 20px; }
  .copy-hint { font-size: 0.75rem; color: #555; margin-top: 4px; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#10003;</div>
  <h1>Payment Successful</h1>
  <p class="sub">Your API key is ready.</p>

  <div class="key-box">
    <div class="key-label">YOUR API KEY</div>
    <div class="key-val" onclick="copyKey(this)" title="Click to copy">{{ key }}</div>
    <div class="copy-hint">Click to copy</div>
  </div>

  <p class="balance">Balance: <span>${{ balance }}</span></p>

  <pre>curl https://api.aipaygen.com/research \\
  -H "Authorization: Bearer {{ key }}" \\
  -H "Content-Type: application/json" \\
  -d '{"topic": "quantum computing"}'</pre>

  <pre># Check balance
curl "https://api.aipaygen.com/auth/status?key={{ key }}"</pre>

  <a href="/buy-credits" class="btn">Buy More Credits</a>
</div>
<script>
function copyKey(el) {
  navigator.clipboard.writeText(el.textContent.trim());
  const orig = el.textContent;
  el.textContent = 'Copied!';
  setTimeout(() => el.textContent = orig, 1500);
}
</script>
</body>
</html>"""


@auth_bp.route("/buy-credits", methods=["GET"])
def buy_credits_page():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured. Set STRIPE_SECRET_KEY in .env"}), 503
    return _BUY_PAGE, 200, {"Content-Type": "text/html"}


@auth_bp.route("/stripe/create-checkout", methods=["POST"])
def stripe_create_checkout():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured"}), 503
    data = request.get_json() or {}
    amount = int(data.get("amount", 20))
    if amount not in (5, 20, 50):
        return jsonify({"error": "amount must be 5, 20, or 50"}), 400
    label = str(data.get("label", ""))[:60]
    existing_key = str(data.get("existing_key", "")).strip()

    # Generate or validate key
    if existing_key and existing_key.startswith("apk_"):
        status = get_key_status(existing_key)
        if not status:
            return jsonify({"error": "key not found"}), 404
        api_key = existing_key
        action = "topup"
    else:
        new_key = generate_key(initial_balance=0.0, label=label)
        api_key = new_key["key"]
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
            client_reference_id=api_key,
            metadata={"api_key": api_key, "amount": str(amount), "action": action, "label": label},
            success_url=f"{BASE_URL}/buy-credits/success?key={api_key}&amount={amount}",
            cancel_url=f"{BASE_URL}/buy-credits",
        )
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
        api_key = meta.get("api_key") or session.get("client_reference_id", "")
        amount = float(meta.get("amount", 0))
        if api_key and api_key.startswith("apk_") and amount > 0:
            topup_key(api_key, amount)
            log_payment("/stripe/topup", amount, session.get("customer_details", {}).get("email", "stripe"))
            # Credit referral commission if ?ref= was passed during checkout
            ref_agent = meta.get("ref_agent", "")
            if ref_agent:
                try:
                    record_conversion(ref_agent, "stripe_purchase", amount)
                except Exception:
                    pass

    return jsonify({"received": True})


@auth_bp.route("/buy-credits/success", methods=["GET"])
def buy_credits_success():
    from security import sanitize_html
    key = request.args.get("key", "")
    amount = request.args.get("amount", "")
    # Validate key format (apk_ + hex chars only)
    if key and not re.match(r'^apk_[a-f0-9]{32}$', key):
        key = ""
    status = get_key_status(key) if key else None
    balance = f"{status['balance_usd']:.2f}" if status else sanitize_html(amount)
    html = _SUCCESS_PAGE.replace("{{ key }}", sanitize_html(key)).replace("{{ balance }}", balance)
    return html, 200, {"Content-Type": "text/html"}
