"""Authentication, API-key management, credits, and Stripe checkout routes."""

import os
import re
import subprocess
import threading
from datetime import datetime

import stripe as _stripe
from flask import Blueprint, request, jsonify

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

_BUY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGen — The Most Powerful AI Toolkit You Can Buy Per Call</title>
<meta name="description" content="106 AI tools, 15 frontier models, one API key. Research, write, code, scrape, analyze — from $0.004/call. No subscriptions.">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 32px 16px; }
  a { color: #818cf8; }
  .wrapper { max-width: 680px; width: 100%; }

  /* Try it banner */
  .try-banner { background: linear-gradient(135deg, #1a1a3e, #0d1a2d); border: 1px solid #2d2d5e; border-radius: 12px; padding: 16px 20px; margin-bottom: 20px; display: flex; align-items: center; gap: 12px; }
  .try-banner .icon { font-size: 1.4rem; }
  .try-banner .text { flex: 1; font-size: 0.85rem; color: #a0a0c0; }
  .try-banner .text strong { color: #e0e0ff; }
  .try-banner a { background: #6366f1; color: #fff; text-decoration: none; padding: 8px 16px; border-radius: 8px; font-size: 0.85rem; font-weight: 600; white-space: nowrap; }

  /* Tabs */
  .tabs { display: flex; gap: 0; margin-bottom: 20px; border-radius: 10px; overflow: hidden; border: 1px solid #2a2a2a; }
  .tab { flex: 1; padding: 12px; text-align: center; background: #141414; color: #888; font-size: 0.85rem; font-weight: 600; cursor: pointer; transition: all 0.15s; border: none; }
  .tab:hover { color: #ccc; }
  .tab.active { background: #6366f1; color: #fff; }

  /* Main card */
  .card { background: #141414; border: 1px solid #2a2a2a; border-radius: 16px; padding: 36px; }
  h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }
  .sub { color: #888; font-size: 0.88rem; margin-bottom: 28px; }
  .plans { display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }
  .plan { flex: 1; min-width: 100px; border: 2px solid #2a2a2a; border-radius: 12px; padding: 18px 12px; cursor: pointer; text-align: center; transition: all 0.15s; position: relative; }
  .plan:hover, .plan.selected { border-color: #6366f1; background: #1a1a2e; }
  .plan .amount { font-size: 1.5rem; font-weight: 800; color: #fff; }
  .plan .credits { font-size: 0.78rem; color: #888; margin-top: 4px; }
  .plan .per-call { font-size: 0.72rem; color: #6366f1; margin-top: 2px; }
  .plan .badge { display: inline-block; background: #6366f1; color: #fff; font-size: 0.68rem; padding: 2px 8px; border-radius: 20px; margin-top: 8px; }
  .plan .badge.green { background: #059669; }
  .plan .badge.starter { background: #f59e0b; }

  /* Specialty packages */
  .pkg-section { display: none; }
  .pkg-section.active { display: block; }
  .pkgs { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 24px; }
  .pkg { border: 2px solid #2a2a2a; border-radius: 12px; padding: 18px; cursor: pointer; transition: all 0.15s; }
  .pkg:hover, .pkg.selected { border-color: #6366f1; background: #1a1a2e; }
  .pkg .pkg-name { font-size: 0.95rem; font-weight: 700; color: #fff; margin-bottom: 4px; }
  .pkg .pkg-price { font-size: 1.1rem; font-weight: 800; color: #6366f1; }
  .pkg .pkg-desc { font-size: 0.75rem; color: #888; margin-top: 6px; line-height: 1.4; }
  .pkg .pkg-tools { font-size: 0.7rem; color: #555; margin-top: 6px; }
  .pkg .pkg-tag { display: inline-block; background: #059669; color: #fff; font-size: 0.65rem; padding: 2px 6px; border-radius: 10px; margin-top: 6px; }

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
    .pkgs { grid-template-columns: 1fr; }
    .features { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="wrapper">
  <div style="display:flex;gap:16px;margin-bottom:20px;font-size:0.85rem"><a href="/" style="color:#888;text-decoration:none">Home</a><a href="/docs" style="color:#888;text-decoration:none">Docs</a><a href="/try" style="color:#888;text-decoration:none">Try Free</a><a href="/security" style="color:#888;text-decoration:none">Security</a></div>
  <div class="try-banner">
    <div class="icon">&#9889;</div>
    <div class="text"><strong>Try before you buy</strong> — test any tool free, no key needed</div>
    <a href="/try">Try it free</a>
  </div>

  <div class="tabs">
    <button class="tab active" onclick="showTab('credits')">Credits</button>
    <button class="tab" onclick="showTab('packages')">Specialty Packages</button>
  </div>

  <!-- Credits Tab -->
  <div class="card pkg-section active" id="tab-credits">
    <h1>Get Your API Key</h1>
    <p class="sub">106 tools. 15 frontier models. Pay per call, not per month.</p>

    <div class="plans">
      <div class="plan" data-amount="1" onclick="selectPlan(this)">
        <div class="amount">$1</div>
        <div class="credits">~160 calls</div>
        <div class="per-call">$0.006/call</div>
        <div class="badge starter">Starter</div>
      </div>
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
      <div class="feat"><span>&#10003;</span> 4,100+ API catalog</div>
      <div class="feat"><span>&#10003;</span> 15 AI models</div>
    </div>
  </div>

  <!-- Specialty Packages Tab -->
  <div class="card pkg-section" id="tab-packages">
    <h1>Specialty Packages</h1>
    <p class="sub">Curated tool bundles for your workflow. All credits work across any tool.</p>

    <div class="pkgs">
      <div class="pkg" data-amount="10" data-label="content-creator" onclick="selectPkg(this)">
        <div class="pkg-name">Content Creator</div>
        <div class="pkg-price">$10</div>
        <div class="pkg-desc">Write articles, social posts, headlines, translations, and proofread — all AI-powered.</div>
        <div class="pkg-tools">write &middot; summarize &middot; translate &middot; social &middot; headline &middot; proofread &middot; rewrite &middot; outline</div>
        <div class="pkg-tag">~1,600 calls</div>
      </div>

      <div class="pkg" data-amount="10" data-label="developer" onclick="selectPkg(this)">
        <div class="pkg-name">Developer</div>
        <div class="pkg-price">$10</div>
        <div class="pkg-desc">Generate code, write tests, explain concepts, create SQL queries, regex, and diagrams.</div>
        <div class="pkg-tools">code &middot; explain &middot; test_cases &middot; sql &middot; regex &middot; diagram &middot; json_schema &middot; mock</div>
        <div class="pkg-tag">~1,600 calls</div>
      </div>

      <div class="pkg" data-amount="10" data-label="data-analyst" onclick="selectPkg(this)">
        <div class="pkg-name">Data Analyst</div>
        <div class="pkg-price">$10</div>
        <div class="pkg-desc">Analyze data, extract insights, classify content, run sentiment analysis, and compare documents.</div>
        <div class="pkg-tools">analyze &middot; extract &middot; classify &middot; compare &middot; sentiment &middot; keywords &middot; score &middot; questions</div>
        <div class="pkg-tag">~1,600 calls</div>
      </div>

      <div class="pkg" data-amount="15" data-label="scraping-pro" onclick="selectPkg(this)">
        <div class="pkg-name">Scraping Pro</div>
        <div class="pkg-price">$15</div>
        <div class="pkg-desc">Scrape Google Maps, Twitter/X, Instagram, TikTok, YouTube, and any website. Plus web search.</div>
        <div class="pkg-tools">scrape/web &middot; scrape/tweets &middot; scrape/instagram &middot; scrape/tiktok &middot; scrape/youtube &middot; scrape/google-maps &middot; web/search</div>
        <div class="pkg-tag">~2,500 calls</div>
      </div>

      <div class="pkg" data-amount="10" data-label="ai-researcher" onclick="selectPkg(this)">
        <div class="pkg-name">AI Researcher</div>
        <div class="pkg-price">$10</div>
        <div class="pkg-desc">Deep research, RAG over documents, fact-checking, debates, decision analysis, and planning.</div>
        <div class="pkg-tools">research &middot; rag &middot; fact &middot; debate &middot; decide &middot; plan &middot; qa &middot; compare</div>
        <div class="pkg-tag">~1,600 calls</div>
      </div>

      <div class="pkg selected" data-amount="25" data-label="full-access" onclick="selectPkg(this)">
        <div class="pkg-name">Full Access</div>
        <div class="pkg-price">$25</div>
        <div class="pkg-desc">Every tool, every model, every endpoint. The complete AI toolkit — nothing held back.</div>
        <div class="pkg-tools">All 106 tools &middot; 15 models &middot; scraping &middot; memory &middot; workflows &middot; agent network</div>
        <div class="pkg-tag">~5,000 calls</div>
      </div>
    </div>

    <div class="field">
      <label>Top up existing key (optional)</label>
      <input type="text" id="pkg_existing_key" placeholder="apk_xxx — leave blank for a new key">
    </div>

    <button class="btn" id="pkg-pay-btn" onclick="pkgCheckout()">&#128274; Pay with Card</button>
    <p class="error" id="pkg-err"></p>
  </div>

  <!-- Shared bottom section -->
  <div class="trust">
    <strong>The most powerful AI toolkit you can buy per call</strong><br>
    106 tools &middot; 15 frontier models &middot; 4100+ APIs &middot; Published on <strong>PyPI</strong> &amp; <strong>MCP Registry</strong><br>
    Credits never expire &middot; 20% bulk discount at $20+ &middot; Secure checkout via Stripe &middot; <a href="/security">Security</a>
  </div>

  <div class="how">
    <span class="step">1.</span> Pick a plan or package &rarr; get your <code>apk_xxx</code> key instantly<br>
    <span class="step">2.</span> Add <code>Authorization: Bearer apk_xxx</code> to any request<br>
    <span class="step">3.</span> Call any of 106 endpoints &mdash; credits deducted per call
  </div>
</div>
<script>
let selectedAmount = 20;
let pkgAmount = 25;
let pkgLabel = 'full-access';

function showTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.pkg-section').forEach(s => s.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  event.target.classList.add('active');
}

function selectPlan(el) {
  document.querySelectorAll('.plan').forEach(p => p.classList.remove('selected'));
  el.classList.add('selected');
  selectedAmount = parseInt(el.dataset.amount);
}

function selectPkg(el) {
  document.querySelectorAll('.pkg').forEach(p => p.classList.remove('selected'));
  el.classList.add('selected');
  pkgAmount = parseInt(el.dataset.amount);
  pkgLabel = el.dataset.label;
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

async function pkgCheckout() {
  const btn = document.getElementById('pkg-pay-btn');
  const err = document.getElementById('pkg-err');
  btn.disabled = true; btn.textContent = 'Redirecting to Stripe...'; err.style.display = 'none';
  try {
    const res = await fetch('/stripe/create-checkout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        amount: pkgAmount,
        label: pkgLabel,
        existing_key: document.getElementById('pkg_existing_key').value.trim(),
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
    key = ""
    amount = ""
    session_id = request.args.get("session_id", "")
    if session_id and STRIPE_SECRET_KEY:
        try:
            session = _stripe.checkout.Session.retrieve(session_id)
            meta = session.get("metadata", {})
            key = meta.get("api_key", "")
            amount = meta.get("amount", "")
        except Exception:
            pass
    # Fallback to query params for legacy links
    if not key:
        key = request.args.get("key", "")
    if not amount:
        amount = request.args.get("amount", "")
    if key and not re.match(r'^apk_[A-Za-z0-9_-]{20,60}$', key):
        key = ""
    status = get_key_status(key) if key else None
    balance = f"{status['balance_usd']:.2f}" if status else sanitize_html(amount)
    html = _SUCCESS_PAGE.replace("{{ key }}", sanitize_html(key)).replace("{{ balance }}", balance)
    return html, 200, {"Content-Type": "text/html"}
