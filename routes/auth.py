"""Authentication, API-key management, credits, and Stripe checkout routes."""

import json
import os
import re
import subprocess
import threading
import time as _time
from datetime import datetime, timezone

import stripe as _stripe
from flask import Blueprint, request, jsonify, render_template, make_response, redirect

from api_keys import (
    generate_key, topup_key, get_key_status, get_key_by_referral_code,
    rotate_key, is_stripe_event_processed, mark_stripe_event_processed,
    has_received_trial_credits, mark_trial_credits_used,
    check_key_gen_rate, record_key_gen, set_allowed_tools, set_daily_spend_limit,
    set_subscription, cancel_subscription, get_subscription_status,
    SUBSCRIPTION_TIERS,
)
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

# ── Scheduled Email Queue (SQLite-backed) ────────────────────────────────────
# Simple table: (id, email, api_key, email_type, send_after, sent, created_at)
# Processed by cron calling /auth/_process-email-queue every 30 min.

_EMAIL_QUEUE_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "email_queue.db")


def _init_email_queue():
    import sqlite3
    with sqlite3.connect(_EMAIL_QUEUE_DB) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS email_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                api_key TEXT DEFAULT '',
                email_type TEXT NOT NULL,
                send_after TEXT NOT NULL,
                sent INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_eq_send ON email_queue(sent, send_after)")


def _schedule_email(email: str, api_key: str, email_type: str, delay_seconds: int):
    """Queue an email to be sent after delay_seconds from now."""
    import sqlite3
    from datetime import timedelta
    _init_email_queue()
    now = datetime.now(timezone.utc)
    send_after = (now + timedelta(seconds=delay_seconds)).isoformat()
    with sqlite3.connect(_EMAIL_QUEUE_DB) as c:
        c.execute(
            "INSERT INTO email_queue (email, api_key, email_type, send_after, sent, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (email, api_key, email_type, send_after, now.isoformat()),
        )


def _process_email_queue():
    """Process pending scheduled emails. Called by cron or internal endpoint."""
    import sqlite3
    _init_email_queue()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_EMAIL_QUEUE_DB) as c:
        c.row_factory = sqlite3.Row
        pending = c.execute(
            "SELECT * FROM email_queue WHERE sent = 0 AND send_after <= ? LIMIT 20",
            (now,),
        ).fetchall()

    sent_ids = []
    for row in pending:
        try:
            if row["email_type"] == "onboarding_day2":
                from email_service import send_onboarding_day2
                send_onboarding_day2(row["email"], row["api_key"])
            elif row["email_type"] == "abandoned_checkout":
                from email_service import send_abandoned_checkout
                send_abandoned_checkout(row["email"])
            elif row["email_type"] == "low_balance":
                from email_service import send_low_balance_reminder
                send_low_balance_reminder(row["email"], row["api_key"], 0.0)
            sent_ids.append(row["id"])
        except Exception as e:
            logger.error("email_queue: failed to send %s to %s: %s", row["email_type"], row["email"], e)

    if sent_ids:
        import sqlite3
        with sqlite3.connect(_EMAIL_QUEUE_DB) as c:
            c.executemany("UPDATE email_queue SET sent = 1 WHERE id = ?", [(i,) for i in sent_ids])

    return len(sent_ids)


# Initialize queue table on import
try:
    _init_email_queue()
except Exception:
    pass


def _cleanup_session_keys():
    now = _time.time()
    stale = [k for k, ts in _session_key_ts.items() if now - ts > _SESSION_KEY_TTL]
    for k in stale:
        _session_key_map.pop(k, None)
        _session_key_ts.pop(k, None)


def _notify_checkout(amount, action, api_key):
    """Log checkout and broadcast wall notification."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = f"[{ts}] CHECKOUT ${amount} ({action}) key={api_key[:12]}..."
    try:
        with open(_NOTIFY_LOG, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    # Write to dedicated payment alert log (easy to tail -f)
    if action == "PAID":
        try:
            alert_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "payments.log")
            with open(alert_file, "a") as f:
                f.write(f"[{ts}] $$$ PAYMENT RECEIVED: ${amount:.2f} | key={api_key[:16]}... $$$\n")
        except Exception:
            pass
    # Broadcast to all terminals (non-blocking)
    def _wall():
        try:
            if action == "PAID":
                wall_msg = f"$$$ AiPayGen PAYMENT: ${amount:.2f} received! key={api_key[:12]}... $$$"
            else:
                wall_msg = f"AiPayGen: ${amount} checkout ({action})"
            subprocess.run(["wall", wall_msg], timeout=3, capture_output=True)
        except Exception:
            pass
    threading.Thread(target=_wall, daemon=True).start()

auth_bp = Blueprint("auth", __name__)


# ── Email + Password Auth ──────────────────────────────────────────────────────

import hashlib
import secrets
import sqlite3
import jwt as _jwt

_JWT_SECRET = os.environ.get("JWT_SECRET", "aipaygen-jwt-2026")
_ACCOUNTS_DB = os.getenv("ACCOUNTS_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "accounts.db"))


def _ensure_password_columns():
    """Add password_hash and salt columns to accounts table if missing."""
    conn = sqlite3.connect(_ACCOUNTS_DB)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()]
        if "password_hash" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN password_hash TEXT")
        if "salt" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN salt TEXT")
        conn.commit()
    finally:
        conn.close()


try:
    _ensure_password_columns()
except Exception:
    pass


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations=600_000).hex()


def _make_jwt(email: str, api_key: str) -> str:
    now = int(_time.time())
    payload = {"email": email, "api_key": api_key, "iat": now, "exp": now + 30 * 86400}
    return _jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ── Auth rate limiter (anti brute-force) ──────────────────────────────────
_auth_attempts = {}  # ip -> [(timestamp, ...)]
_AUTH_RATE_LIMIT = 10  # max attempts per IP
_AUTH_RATE_WINDOW = 300  # in 5 minutes

def _check_auth_rate(ip):
    """Return True if IP is rate-limited for auth endpoints."""
    if not ip or ip in ("127.0.0.1", "::1"):
        return False
    now = _time.time()
    attempts = _auth_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _AUTH_RATE_WINDOW]
    if len(attempts) >= _AUTH_RATE_LIMIT:
        _auth_attempts[ip] = attempts
        return True
    attempts.append(now)
    _auth_attempts[ip] = attempts
    return False


@auth_bp.route("/auth/register", methods=["POST"])
def auth_register():
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
    if _check_auth_rate(ip):
        return jsonify({"error": "Too many attempts. Please wait a few minutes."}), 429
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not _EMAIL_RE.match(email):
        return jsonify({"error": "Invalid email format"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    ip = request.headers.get("CF-Connecting-IP", request.remote_addr)

    # Check if account already exists with a password
    conn = sqlite3.connect(_ACCOUNTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
        if row and row["password_hash"]:
            return jsonify({"error": "Account already exists. Please log in."}), 409

        salt = secrets.token_hex(16)
        pw_hash = _hash_password(password, salt)
        now = datetime.now(timezone.utc).isoformat()

        if row:
            # Account exists (e.g. from magic link) but no password — set it
            conn.execute(
                "UPDATE accounts SET password_hash=?, salt=? WHERE email=?",
                (pw_hash, salt, email),
            )
            conn.commit()
            account_id = row["id"]
        else:
            conn.execute(
                "INSERT INTO accounts (email, created_at, password_hash, salt) VALUES (?, ?, ?, ?)",
                (email, now, pw_hash, salt),
            )
            conn.commit()
            account_id = conn.execute("SELECT id FROM accounts WHERE email=?", (email,)).fetchone()["id"]
    finally:
        conn.close()

    # Generate API key with $0.10 trial balance
    from api_keys import generate_key
    from accounts import link_key_to_account
    if has_received_trial_credits(ip):
        trial_balance = 0.0
    else:
        trial_balance = 0.10
        mark_trial_credits_used(ip)
    key_data = generate_key(initial_balance=trial_balance)
    link_key_to_account(account_id, key_data["key"])

    token = _make_jwt(email, key_data["key"])
    return jsonify({
        "jwt": token,
        "api_key": key_data["key"],
        "email": email,
        "balance_usd": key_data["balance_usd"],
    })


@auth_bp.route("/auth/login", methods=["POST"])
def auth_login():
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
    if _check_auth_rate(ip):
        return jsonify({"error": "Too many login attempts. Please wait a few minutes."}), 429
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    conn = sqlite3.connect(_ACCOUNTS_DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
    finally:
        conn.close()

    if not row or not row["password_hash"] or not row["salt"]:
        return jsonify({"error": "Invalid email or password"}), 401

    if _hash_password(password, row["salt"]) != row["password_hash"]:
        # Check legacy SHA256 hash for migration
        legacy = hashlib.sha256((password + row["salt"]).encode()).hexdigest()
        if legacy != row["password_hash"]:
            return jsonify({"error": "Invalid email or password"}), 401
        # Migrate to PBKDF2
        try:
            import sqlite3 as _sq
            new_hash = _hash_password(password, row["salt"])
            with _sq.connect(_ACCOUNTS_DB) as c:
                c.execute("UPDATE accounts SET password_hash = ? WHERE id = ?", (new_hash, row["id"]))
        except Exception:
            pass

    # Update last login
    from accounts import update_last_login, get_account_keys
    update_last_login(row["id"])

    # Get existing API key
    keys = get_account_keys(row["id"])
    if keys:
        api_key = keys[0]["api_key"]
    else:
        # No key linked — generate one
        from api_keys import generate_key
        from accounts import link_key_to_account
        key_data = generate_key(initial_balance=0.0)
        link_key_to_account(row["id"], key_data["key"])
        api_key = key_data["key"]

    # Get balance
    status = get_key_status(api_key)
    balance = status["balance_usd"] if status else 0.0

    token = _make_jwt(email, api_key)
    return jsonify({
        "jwt": token,
        "api_key": api_key,
        "email": email,
        "balance_usd": balance,
    })


# ── Ad Reward (server-side bonus) ─────────────────────────────────────────────

_ad_reward_cache = {}  # {ip: date_str -> count} — rate limit + cooldown
_ad_reward_timestamps = {}  # {ip -> last_reward_time} — minimum interval


@auth_bp.route("/auth/ad-reward", methods=["POST"])
def auth_ad_reward():
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Rate limit: max 3 ad rewards per IP per day (reduced from 10 to limit abuse)
    cache_key = f"{ip}:{today}"
    count = _ad_reward_cache.get(cache_key, 0)
    if count >= 3:
        return jsonify({"error": "Maximum ad rewards reached today. Get an API key for unlimited access.", "get_key": "/get-key"}), 429

    # Cooldown: minimum 30 seconds between rewards (prevents rapid-fire abuse)
    now = _time.time()
    last = _ad_reward_timestamps.get(ip, 0)
    if now - last < 30:
        return jsonify({"error": "Please wait before claiming another reward."}), 429
    _ad_reward_timestamps[ip] = now

    from agent_network import grant_ad_bonus
    result = grant_ad_bonus(ip)
    _ad_reward_cache[cache_key] = count + 1
    return jsonify({"ok": True, "bonus_calls": 1, "calls_used": result["calls_used"], "calls_available": result.get("calls_available", 0), "rewards_remaining": 3 - count - 1})


# ── Quick Key (zero-click key generation page) ────────────────────────────────

@auth_bp.route("/quick-key")
def quick_key_page():
    """Auto-generate a key on page visit and display it immediately."""
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr)
    if not check_key_gen_rate(ip, max_per_day=10):
        return '<html><body style="background:#0a0c10;color:#e0e0e0;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:sans-serif"><div style="text-align:center"><h2>Daily limit reached</h2><p><a href="/buy-credits" style="color:#6366f1">Buy credits</a> or try again tomorrow.</p><p style="margin-top:12px"><a href="/market" style="color:#d4a853">Browse the Agent Marketplace →</a></p></div></body></html>', 429
    if has_received_trial_credits(ip):
        trial_balance = 0.0
    else:
        trial_balance = 0.10
        mark_trial_credits_used(ip)
    record_key_gen(ip)
    key_data = generate_key(initial_balance=trial_balance, label="quick-key", source="quick_key_page")
    funnel_log_event("key_generated", endpoint="/quick-key", ip=ip, user_agent=request.headers.get("User-Agent", ""), metadata=json.dumps({"source": "quick_key_page", "balance": trial_balance}))
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Free API Key — AiPayGen</title>
<meta name="description" content="Get a free AiPayGen API key instantly with $0.10 trial credits. No sign-up needed. Start using 65+ AI tools in seconds.">
<meta property="og:title" content="Get Free API Key — AiPayGen">
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:-apple-system,sans-serif;background:#0a0c10;color:#e0e0e0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:#141820;border:1px solid #1e2530;border-radius:16px;padding:40px;max-width:520px;width:100%;text-align:center}}
h1{{color:#00ff9d;font-size:1.4rem;margin-bottom:8px}}p{{color:#8b949e;margin-bottom:20px;font-size:0.9rem}}
.key{{background:#0d1117;border:1px solid #00ff9d33;border-radius:8px;padding:14px;font-family:'IBM Plex Mono',monospace;font-size:0.85rem;color:#00ff9d;word-break:break-all;margin-bottom:16px;cursor:pointer}}
.key:hover{{background:#0d1117cc;border-color:#00ff9d}}
.bal{{color:#00ff9d;font-size:1.8rem;font-weight:700;margin-bottom:4px}}.bal-label{{color:#8b949e;font-size:0.8rem;margin-bottom:24px}}
.steps{{text-align:left;background:#0d111799;border-radius:8px;padding:16px;margin-bottom:20px;font-size:0.82rem;line-height:1.6}}
.steps code{{background:#1e2530;padding:2px 6px;border-radius:4px;color:#e0e0e0}}
a.btn{{display:inline-block;background:#6366f1;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600;margin:4px}}
a.btn-outline{{background:transparent;border:1px solid #6366f1;color:#a78bfa}}
</style></head><body>
<div class="card">
<h1>Your Free API Key</h1>
<p>Click to copy — use this for all AiPayGen API calls</p>
<div class="key" onclick="navigator.clipboard.writeText('{key_data["key"]}');this.textContent='Copied!';setTimeout(()=>this.textContent='{key_data["key"]}',2000)">{key_data["key"]}</div>
<div class="bal">${trial_balance:.2f}</div>
<div class="bal-label">Free trial credits (~{int(trial_balance/0.006)} calls)</div>
<div class="steps">
<strong>Use it in 3 ways:</strong><br>
1. <strong>API:</strong> Add header <code>Authorization: Bearer {key_data["key"][:20]}...</code><br>
2. <strong>MCP:</strong> Set <code>AIPAYGEN_API_KEY={key_data["key"][:20]}...</code> env var<br>
3. <strong>Web:</strong> Paste at <a href="/playground" style="color:#6366f1">/playground</a>
</div>
<a class="btn" href="/buy-credits">Buy More Credits</a>
<a class="btn btn-outline" href="/try">Try Tools Now</a>
<div style="margin-top:24px;padding:16px;background:#0d111799;border-radius:8px;border:1px solid #1e2530;text-align:center">
<p style="color:#d4a853;font-weight:600;margin-bottom:8px">Browse the Agent Marketplace</p>
<p style="color:#8b949e;font-size:0.82rem;margin-bottom:12px">Use your key to try 72+ AI agents — trading, research, code, content</p>
<a href="/market" style="display:inline-block;background:#d4a853;color:#0a0c10;padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:600;font-size:0.85rem">Browse Agents →</a>
</div>
</div></body></html>"""
    return html, 200, {"Content-Type": "text/html", "Cache-Control": "no-store"}


# ── Auth / Key Management ─────────────────────────────────────────────────────

@auth_bp.route("/auth/generate-key", methods=["POST"])
def auth_generate_key():
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr)
    if not check_identity_rate_limit(ip):
        resp = jsonify({"error": "rate_limited", "message": "Too many key generation requests. Max 10/min."})
        resp.headers["Retry-After"] = "60"
        return resp, 429
    # Max 5 keys per IP per day
    if not check_key_gen_rate(ip, max_per_day=5):
        resp = jsonify({"error": "rate_limited", "message": "Maximum 5 API keys per IP per day. Contact support for higher limits."})
        resp.headers["Retry-After"] = "60"
        return resp, 429
    data = request.get_json() or {}
    label = data.get("label", "")
    source = data.get("source", request.cookies.get("aipaygen_ref", "api-direct"))
    email = (data.get("email") or "").strip().lower()
    ref_code = data.get("ref", "") or request.args.get("ref", "") or request.cookies.get("aipaygen_ref", "")
    # Trial credits: $0.10 only for first key per IP, $0 for subsequent
    if has_received_trial_credits(ip):
        trial_balance = 0.0
    else:
        trial_balance = 0.10
        mark_trial_credits_used(ip)
    record_key_gen(ip)
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
                                 metadata=json.dumps({"ref_code": ref_code, "referrer_key": referrer["key"][:12]}),
                                 user_agent=request.headers.get("User-Agent", ""))
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
        # Send welcome email immediately on free key generation
        try:
            from email_service import send_welcome_email
            send_welcome_email(email, key_data["key"])
        except Exception:
            pass
        # Schedule day-2 onboarding follow-up (48 hours)
        try:
            _schedule_email(email, key_data["key"], "onboarding_day2", delay_seconds=48 * 3600)
        except Exception:
            pass
    api_key = key_data["key"]
    try:
        funnel_log_event("key_generated", endpoint="/auth/generate-key",
                         ip=ip, metadata=json.dumps({"source": source}),
                         user_agent=request.headers.get("User-Agent", ""))
    except Exception:
        pass
    # Track A/B conversion
    try:
        from ab_testing import track_conversion, get_variant
        ab_variant = get_variant("landing_hero_v1", ip)
        track_conversion("landing_hero_v1", ab_variant, ip, event="key_generated")
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
            "free_calls": 0,
            "note": f"Your key includes ${trial_balance:.2f} trial credits{f' (~{int(trial_balance/0.006)} calls)' if trial_balance > 0 else ''}. {'Buy more' if trial_balance > 0 else 'Add credits'} at /buy-credits.",
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
    key = request.args.get("key") or ""
    if not key and request.method == "POST":
        key = (request.get_json(silent=True) or {}).get("key", "")
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
                            "unit_amount": int(round(amount * 100)),
                            "product_data": {"name": f"AiPayGen API Credits (${amount})"},
                        },
                        "quantity": 1,
                    }],
                    mode="payment",
                    success_url=f"{BASE_URL}/buy-credits/success?session_id={{CHECKOUT_SESSION_ID}}",
                    cancel_url=f"{BASE_URL}/buy-credits",
                    metadata={"amount": str(amount), "action": "new", "label": label},
                )
                _ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
                if _ip not in ("127.0.0.1", "::1"):
                    funnel_log_event("checkout_started", endpoint="/credits/buy",
                                     ip=_ip, metadata=f'{{"amount_usd": {amount}}}',
                                     user_agent=request.headers.get("User-Agent", ""))
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
        _buy_ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
        _ua = request.headers.get("User-Agent", "")
        funnel_log_event("credits_bought", endpoint="/credits/buy",
                         ip=_buy_ip,
                         metadata=f'{{"amount_usd": {amount}}}', user_agent=_ua)
        funnel_log_event("key_generated", endpoint="/credits/buy",
                         ip=_buy_ip,
                         user_agent=_ua)
    except Exception:
        pass
    # Track A/B conversion
    try:
        from ab_testing import track_conversion, get_variant
        ab_variant = get_variant("landing_hero_v1", _buy_ip)
        track_conversion("landing_hero_v1", ab_variant, _buy_ip, event="credits_bought")
    except Exception:
        pass
    return jsonify({
        "key": key_data["key"],
        "balance_usd": amount,
        "label": label,
        "pricing": "Use 'X-Pricing: metered' header for token-based billing",
    })


# ── Stripe Checkout & Webhook ─────────────────────────────────────────────────



@auth_bp.route("/auth/rotate-key", methods=["POST"])
@require_api_key
def auth_rotate_key():
    """Rotate an API key — generates a new key, transfers balance, deactivates old key."""
    bearer = (request.headers.get("Authorization", "")[7:]
              if request.headers.get("Authorization", "").startswith("Bearer ") else "")
    if not bearer or not bearer.startswith("apk_"):
        return jsonify({"error": "API key required"}), 401
    result = rotate_key(bearer)
    if not result:
        return jsonify({"error": "Key not found or already deactivated"}), 404
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
    try:
        funnel_log_event("key_rotated", ip=ip, endpoint="/auth/rotate-key")
    except Exception:
        pass
    return jsonify(result)


@auth_bp.route("/auth/set-allowed-tools", methods=["POST"])
@require_api_key
def auth_set_allowed_tools():
    """Set allowed tools for an API key. Pass empty list to remove restrictions."""
    bearer = (request.headers.get("Authorization", "")[7:]
              if request.headers.get("Authorization", "").startswith("Bearer ") else "")
    if not bearer:
        return jsonify({"error": "API key required"}), 401
    data = request.get_json() or {}
    tools = data.get("tools", [])
    if not isinstance(tools, list):
        return jsonify({"error": "tools must be a list of tool names"}), 400
    if set_allowed_tools(bearer, tools):
        return jsonify({"allowed_tools": tools, "message": "Updated. Only these tools can be called with this key." if tools else "All tools are now allowed."})
    return jsonify({"error": "Key not found"}), 404


@auth_bp.route("/auth/set-daily-limit", methods=["POST"])
@require_api_key
def auth_set_daily_limit():
    """Set daily spending limit for an API key (default $10, max $50)."""
    bearer = (request.headers.get("Authorization", "")[7:]
              if request.headers.get("Authorization", "").startswith("Bearer ") else "")
    if not bearer:
        return jsonify({"error": "API key required"}), 401
    data = request.get_json() or {}
    limit = float(data.get("limit_usd", 10.0))
    if limit < 0.01 or limit > 50.0:
        return jsonify({"error": "limit_usd must be between $0.01 and $50.00"}), 400
    if set_daily_spend_limit(bearer, limit):
        return jsonify({"daily_spend_limit": limit})
    return jsonify({"error": "Key not found"}), 404


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
    # Block SSRF: reject internal IPs, localhost, and dangerous ports
    from urllib.parse import urlparse as _urlparse
    _wh_host = (_urlparse(url).hostname or "").lower()
    if _wh_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or _wh_host.startswith("10.") or _wh_host.startswith("192.168.") or _wh_host.startswith("172."):
        return jsonify({"error": "Internal URLs not allowed"}), 400
    threshold = float(data.get("threshold", 0.50))
    from webhook_dispatch import register_webhook
    wh_id = register_webhook(api_key, url, events, threshold=threshold)
    if wh_id is None:
        return jsonify({"error": "Failed to register webhook"}), 400
    return jsonify({"webhook_id": wh_id, "url": url, "events": events, "threshold": threshold})


@auth_bp.route("/api/webhooks", methods=["POST"])
def api_register_webhook():
    """Convenience alias: POST /api/webhooks with {url, event, threshold}."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer apk_"):
        return jsonify({"error": "API key required"}), 401
    api_key = auth[7:]
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    event = data.get("event", "")
    events = data.get("events", [event] if event else [])
    if not url or not events:
        return jsonify({"error": "url and event(s) required"}), 400
    if not url.startswith("https://"):
        return jsonify({"error": "Invalid URL — must be HTTPS"}), 400
    threshold = float(data.get("threshold", 0.50))
    from webhook_dispatch import register_webhook
    wh_id = register_webhook(api_key, url, events, threshold=threshold)
    if wh_id is None:
        return jsonify({"error": "Failed to register webhook"}), 400
    return jsonify({"webhook_id": wh_id, "url": url, "events": events, "threshold": threshold})


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


# ── Checkout rate limiter (anti card-testing) ─────────────────────────────
_checkout_attempts = {}  # ip -> [(timestamp, ...)]
_CHECKOUT_RATE_LIMIT = 5  # max attempts per IP
_CHECKOUT_RATE_WINDOW = 300  # in 5 minutes

def _check_checkout_rate(ip):
    """Return True if IP is rate-limited."""
    now = _time.time()
    attempts = _checkout_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _CHECKOUT_RATE_WINDOW]
    _checkout_attempts[ip] = attempts
    if len(attempts) >= _CHECKOUT_RATE_LIMIT:
        return True
    attempts.append(now)
    _checkout_attempts[ip] = attempts
    return False


@auth_bp.route("/stripe/create-checkout", methods=["POST"])
def stripe_create_checkout():
    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured"}), 503

    # Rate limit checkout creation to block card-testing bots
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
    if ip and ip not in ("127.0.0.1", "::1") and _check_checkout_rate(ip):
        logger.warning("Checkout rate limited: %s", ip)
        return jsonify({"error": "Too many checkout attempts. Please wait a few minutes."}), 429

    data = request.get_json() or {}
    # Accept both integer and float amounts for $0.50 support
    raw_amount = data.get("amount")
    if raw_amount is None:
        return jsonify({"error": "missing_amount", "message": "Amount is required. Choose: $0.50, $1, $5, $9, $10, $15, $20, $25, $29, $50, $79"}), 400
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid amount"}), 400
    allowed_amounts = (0.50, 1, 5, 9, 10, 15, 20, 25, 29, 50, 79)
    if amount not in allowed_amounts:
        return jsonify({"error": "invalid_amount", "message": f"Amount must be one of: {', '.join(f'${a}' for a in allowed_amounts)}"}), 400
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
        calls_estimate = int(amount * 100)
        checkout_kwargs = dict(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"AiPayGen API Credits — ${amount:.2f}",
                        "description": f"Prepaid credits for api.aipaygen.com. ~{calls_estimate} API calls.",
                    },
                    "unit_amount": int(round(amount * 100)),  # cents
                },
                "quantity": 1,
            }],
            mode="payment",
            client_reference_id=existing_key or "new",
            metadata={"amount": str(amount), "action": action, "label": label,
                       "ref_source": request.cookies.get("aipaygen_ref", "direct"),
                       "ref_agent": data.get("ref_agent", "") or request.cookies.get("aipaygen_ref_agent", ""),
                       **({"api_key": existing_key} if existing_key else {}),
                       **({"customer_email": email} if email else {})},
            success_url=f"{BASE_URL}/buy-credits/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/buy-credits?abandoned=1",
            # Anti-fraud: require billing address to deter card testers
            billing_address_collection="required",
            # Expire checkout quickly to reduce abuse window
            expires_at=int(_time.time()) + 1800,  # 30 minutes
        )
        # Pre-fill email in Stripe checkout if we have it
        if email:
            checkout_kwargs["customer_email"] = email
        session = _stripe.checkout.Session.create(**checkout_kwargs)
        ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
        if ip not in ("127.0.0.1", "::1"):
            funnel_log_event("checkout_started", endpoint="/stripe/create-checkout",
                             ip=ip, metadata=json.dumps({"amount_usd": amount, "email": email or "", "session_id": session.id}),
                             user_agent=request.headers.get("User-Agent", ""))
        # Schedule abandoned checkout follow-up (1 hour) if email provided
        if email:
            try:
                _schedule_email(email, "", "abandoned_checkout", delay_seconds=3600)
            except Exception:
                pass
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

    # Idempotency: skip already-processed events
    event_id = event.get("id", "")
    if event_id and is_stripe_event_processed(event_id):
        logger.info("Skipping duplicate Stripe event: %s", event_id)
        return jsonify({"received": True, "duplicate": True})
    # Handle subscription invoice paid (monthly renewal)
    if event["type"] == "invoice.paid":
        invoice = event["data"]["object"]
        sub_id = invoice.get("subscription", "")
        if sub_id:
            # Find key with this subscription_id and reset calls
            try:
                import sqlite3 as _sq
                from api_keys import DB_PATH as _keys_db, reset_subscription_calls
                conn = _sq.connect(_keys_db)
                conn.row_factory = _sq.Row
                row = conn.execute(
                    "SELECT key FROM api_keys WHERE subscription_id = ? AND is_active = 1",
                    (sub_id,),
                ).fetchone()
                conn.close()
                if row:
                    reset_subscription_calls(row["key"])
                    logger.info("Subscription renewed for key %s...", row["key"][:12])
            except Exception as e:
                logger.error("Subscription renewal processing failed: %s", e)
        if event_id:
            mark_stripe_event_processed(event_id)
        return jsonify({"received": True})

    # Handle subscription canceled
    if event["type"] == "customer.subscription.deleted":
        sub_obj = event["data"]["object"]
        sub_id = sub_obj.get("id", "")
        if sub_id:
            try:
                import sqlite3 as _sq
                from api_keys import DB_PATH as _keys_db
                conn = _sq.connect(_keys_db)
                conn.row_factory = _sq.Row
                row = conn.execute(
                    "SELECT key FROM api_keys WHERE subscription_id = ? AND is_active = 1",
                    (sub_id,),
                ).fetchone()
                conn.close()
                if row:
                    cancel_subscription(row["key"])
                    logger.info("Subscription canceled for key %s...", row["key"][:12])
            except Exception as e:
                logger.error("Subscription cancellation processing failed: %s", e)
        if event_id:
            mark_stripe_event_processed(event_id)
        return jsonify({"received": True})

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {})

        # Handle subscription checkout
        if meta.get("action") == "subscription":
            tier = meta.get("tier", "")
            api_key = meta.get("api_key", "")
            sub_id = session.get("subscription", "")
            customer_email = (session.get("customer_details", {}).get("email", "")
                              or meta.get("customer_email", ""))

            if not api_key or not api_key.startswith("apk_"):
                # Create new key for subscriber
                new_key = generate_key(initial_balance=0.0, label=f"subscription-{tier}", source="stripe-subscription")
                api_key = new_key["key"]
                _cleanup_session_keys()
                _session_key_map[session["id"]] = api_key
                _session_key_ts[session["id"]] = _time.time()
                try:
                    _stripe.checkout.Session.modify(session["id"], metadata={**meta, "api_key": api_key})
                except Exception:
                    pass

            # Activate subscription
            from datetime import timedelta
            reset_date = (datetime.now(timezone.utc).replace(day=1) + timedelta(days=32)).replace(day=1).strftime("%Y-%m-%d")
            set_subscription(api_key, tier, sub_id, reset_date)

            _notify_checkout(SUBSCRIPTION_TIERS[tier]["price_usd"], f"SUBSCRIPTION-{tier.upper()}", api_key)
            create_notification(api_key, "subscription_activated",
                                f"Welcome to {tier.title()} plan! {SUBSCRIPTION_TIERS[tier]['monthly_calls']} calls/month.")

            if customer_email and api_key:
                try:
                    from email_service import send_api_key_email, send_welcome_email
                    from accounts import create_or_get_account, link_key_to_account
                    send_api_key_email(customer_email, api_key, 0)
                    send_welcome_email(customer_email, api_key)
                    acct = create_or_get_account(customer_email)
                    link_key_to_account(acct["id"], api_key)
                except Exception:
                    pass

            ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
            try:
                funnel_log_event("subscription_activated", endpoint="/stripe/webhook",
                                 ip=ip, metadata=json.dumps({"tier": tier}),
                                 user_agent=request.headers.get("User-Agent", ""))
            except Exception:
                pass
            return jsonify({"received": True})

        amount = float(meta.get("amount", 0))
        # Validate metadata amount against actual Stripe charge (cents -> dollars)
        stripe_amount = session.get("amount_total", 0) / 100
        if amount != stripe_amount:
            logger.warning("Stripe amount mismatch: metadata=%.2f, actual=%.2f (session %s)",
                           amount, stripe_amount, session.get("id", ""))
            amount = stripe_amount
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

            # Cancel any pending abandoned-checkout email for this customer
            customer_email = (session.get("customer_details", {}).get("email", "")
                              or meta.get("customer_email", ""))
            if customer_email:
                try:
                    import sqlite3 as _sq
                    with _sq.connect(_EMAIL_QUEUE_DB) as _c:
                        _c.execute(
                            "UPDATE email_queue SET sent = 1 WHERE email = ? AND email_type = 'abandoned_checkout' AND sent = 0",
                            (customer_email,),
                        )
                except Exception as e:
                    logger.warning("Failed to cancel abandoned checkout email: %s", e)

            # Send API key email and link to account
            if customer_email and api_key:
                try:
                    from email_service import send_api_key_email, send_welcome_email
                    from accounts import create_or_get_account, link_key_to_account
                    bal = float(meta.get("amount", 0))
                    send_api_key_email(customer_email, api_key, bal)
                    send_welcome_email(customer_email, api_key)
                    acct = create_or_get_account(customer_email)
                    link_key_to_account(acct["id"], api_key)
                except Exception as e:
                    logger.error("Failed to send key email to %s: %s", customer_email, e)

            # Credit referral commission if ?ref= was passed during checkout
            ref_agent = meta.get("ref_agent", "")
            if ref_agent:
                try:
                    record_conversion(ref_agent, "stripe_purchase", amount)
                except Exception:
                    pass

    # Mark event as processed AFTER all business logic succeeds
    # so Stripe retries if we crash mid-processing
    if event_id:
        mark_stripe_event_processed(event_id)

    return jsonify({"received": True})


# ── Refund Credit Redemption ───────────────────────────────────────────────

@auth_bp.route("/redeem-refund", methods=["POST"])
def redeem_refund():
    """Redeem a refund credit code to add balance to an API key."""
    data = request.get_json() or {}
    code = data.get("code", "").strip()
    api_key = data.get("api_key", "").strip()

    if not code or not api_key:
        return jsonify({"error": "code and api_key required"}), 400

    import sqlite3 as _sq
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "refunds.db")
    conn = _sq.connect(db_path)
    conn.row_factory = _sq.Row
    row = conn.execute("SELECT * FROM refund_credits WHERE code = ? AND redeemed = 0", (code,)).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Invalid or already redeemed code"}), 400

    amount = row["amount_usd"]

    # Mark as redeemed
    conn.execute("UPDATE refund_credits SET redeemed = 1, redeemed_at = datetime('now') WHERE code = ?", (code,))
    conn.commit()
    conn.close()

    # Add balance to the API key
    result = topup_key(api_key, amount)
    if result.get("error"):
        return jsonify({"error": "Failed to apply credit: " + result["error"]}), 400

    return jsonify({"ok": True, "credited": amount, "message": f"${amount:.2f} added to your balance"})


# ── Subscription Endpoints ─────────────────────────────────────────────────

# Stripe Price IDs are created on first use and cached
_SUBSCRIPTION_PRICE_IDS = {}


def _get_or_create_stripe_price(tier: str) -> str:
    """Get or create a Stripe recurring Price for a subscription tier."""
    if tier in _SUBSCRIPTION_PRICE_IDS:
        return _SUBSCRIPTION_PRICE_IDS[tier]
    tier_info = SUBSCRIPTION_TIERS[tier]
    # Search for existing product
    try:
        products = _stripe.Product.list(limit=100)
        for prod in products.auto_paging_iter():
            if prod.metadata.get("aipaygen_sub_tier") == tier and prod.active:
                prices = _stripe.Price.list(product=prod.id, active=True, limit=1)
                if prices.data:
                    _SUBSCRIPTION_PRICE_IDS[tier] = prices.data[0].id
                    return prices.data[0].id
    except Exception:
        pass
    # Create product + price
    product = _stripe.Product.create(
        name=f"AiPayGen {tier.title()} Plan",
        description=f"{tier_info['monthly_calls']} AI calls/month, all 65+ tools",
        metadata={"aipaygen_sub_tier": tier},
    )
    price = _stripe.Price.create(
        product=product.id,
        unit_amount=int(round(tier_info["price_usd"] * 100)),
        currency="usd",
        recurring={"interval": "month"},
    )
    _SUBSCRIPTION_PRICE_IDS[tier] = price.id
    return price.id


@auth_bp.route("/subscribe", methods=["GET", "POST"])
def subscribe_page_or_create():
    """GET: render subscribe page. POST: create Stripe subscription checkout."""
    if request.method == "GET":
        resp = make_response(render_template("subscribe.html"))
        resp.headers["Content-Type"] = "text/html"
        return resp

    if not STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured"}), 503

    data = request.get_json() or {}
    tier = data.get("tier", "").lower()
    if tier not in SUBSCRIPTION_TIERS:
        return jsonify({"error": f"Invalid tier. Choose: {', '.join(SUBSCRIPTION_TIERS.keys())}"}), 400

    existing_key = str(data.get("existing_key", "")).strip()
    email = str(data.get("email", "")).strip().lower()[:120]

    # Validate existing key if provided
    if existing_key and existing_key.startswith("apk_"):
        status = get_key_status(existing_key)
        if not status:
            return jsonify({"error": "API key not found"}), 404
    else:
        existing_key = ""

    try:
        price_id = _get_or_create_stripe_price(tier)
        checkout_kwargs = dict(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            metadata={
                "tier": tier,
                "action": "subscription",
                **({"api_key": existing_key} if existing_key else {}),
                **({"customer_email": email} if email else {}),
            },
            success_url=f"{BASE_URL}/subscribe/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/subscribe?canceled=1",
        )
        if email:
            checkout_kwargs["customer_email"] = email
        session = _stripe.checkout.Session.create(**checkout_kwargs)
        ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
        if ip not in ("127.0.0.1", "::1"):
            funnel_log_event("subscription_checkout_started", endpoint="/subscribe",
                             ip=ip, metadata=json.dumps({"tier": tier}),
                             user_agent=request.headers.get("User-Agent", ""))
        # Schedule abandoned checkout follow-up for subscription too
        if email:
            try:
                _schedule_email(email, "", "abandoned_checkout", delay_seconds=3600)
            except Exception:
                pass
        return jsonify({"url": session.url, "session_id": session.id})
    except Exception as e:
        logger.error("Stripe subscription checkout failed: %s", e)
        return jsonify({"error": "Payment processing failed"}), 500


@auth_bp.route("/subscribe/success", methods=["GET"])
def subscribe_success():
    session_id = request.args.get("session_id", "")
    return render_template("buy_credits_success.html",
                           api_key=_session_key_map.get(session_id, ""),
                           session_id=session_id,
                           subscription=True), 200, {"Content-Type": "text/html"}


@auth_bp.route("/subscription/status", methods=["GET"])
@require_api_key
def subscription_status():
    """Check subscription details for the authenticated API key."""
    bearer = (request.headers.get("Authorization", "")[7:]
              if request.headers.get("Authorization", "").startswith("Bearer ") else "")
    if not bearer:
        return jsonify({"error": "API key required"}), 401
    sub = get_subscription_status(bearer)
    if not sub:
        return jsonify({"subscription": None, "message": "No active subscription. Visit /subscribe to get started."})
    return jsonify({"subscription": sub})


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
    session_id = request.args.get("session_id", "")
    # If we already know the key, pass it to the template for instant display
    api_key = _session_key_map.get(session_id, "")
    return render_template("buy_credits_success.html", api_key=api_key, session_id=session_id), 200, {"Content-Type": "text/html"}


@auth_bp.route("/auth/_process-email-queue", methods=["POST"])
@require_admin
def process_email_queue():
    """Process pending scheduled emails. Called by cron every 30 min."""
    count = _process_email_queue()
    return jsonify({"processed": count})


# ── Usage Dashboard & API ────────────────────────────────────────────────────


def _get_usage_data(api_key):
    """Fetch usage data for an API key from api_keys.db and tool_usage.db."""
    import sqlite3
    status = get_key_status(api_key)
    if not status:
        return None

    base_dir = os.path.dirname(os.path.dirname(__file__))
    tool_usage_db = os.path.join(base_dir, "tool_usage.db")

    # Top tools for this key
    top_tools = []
    try:
        conn = sqlite3.connect(tool_usage_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT tool_name, count, last_used FROM tool_usage WHERE api_key = ? ORDER BY count DESC LIMIT 10",
            (api_key,),
        ).fetchall()
        top_tools = [{"tool": r["tool_name"], "calls": r["count"], "last_used": r["last_used"]} for r in rows]
        conn.close()
    except Exception:
        pass

    # Calls today for this key
    calls_today = 0
    try:
        conn = sqlite3.connect(tool_usage_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT SUM(count) as today_count FROM tool_usage WHERE api_key = ? AND date(last_used) = date('now')",
            (api_key,),
        ).fetchone()
        calls_today = row["today_count"] or 0
        conn.close()
    except Exception:
        pass

    # Recent call history (last 20 tools used)
    recent = []
    try:
        conn = sqlite3.connect(tool_usage_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT tool_name, count, last_used FROM tool_usage WHERE api_key = ? ORDER BY last_used DESC LIMIT 20",
            (api_key,),
        ).fetchall()
        recent = [{"tool": r["tool_name"], "calls": r["count"], "last_used": r["last_used"]} for r in rows]
        conn.close()
    except Exception:
        pass

    # Calls this week (last 7 days)
    calls_week = 0
    try:
        conn = sqlite3.connect(tool_usage_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT SUM(count) as wk FROM tool_usage WHERE api_key = ? AND last_used >= datetime('now', '-7 days')",
            (api_key,),
        ).fetchone()
        calls_week = row["wk"] or 0
        conn.close()
    except Exception:
        pass

    # Calls this month (last 30 days)
    calls_month = 0
    try:
        conn = sqlite3.connect(tool_usage_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT SUM(count) as mo FROM tool_usage WHERE api_key = ? AND last_used >= datetime('now', '-30 days')",
            (api_key,),
        ).fetchone()
        calls_month = row["mo"] or 0
        conn.close()
    except Exception:
        pass

    # Calls last 90 days
    calls_90d = 0
    try:
        conn = sqlite3.connect(tool_usage_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT SUM(count) as q FROM tool_usage WHERE api_key = ? AND last_used >= datetime('now', '-90 days')",
            (api_key,),
        ).fetchone()
        calls_90d = row["q"] or 0
        conn.close()
    except Exception:
        pass

    # Spending this week and month
    spent_week = 0
    spent_month = 0
    try:
        conn = sqlite3.connect(tool_usage_db)
        conn.row_factory = sqlite3.Row
        avg_cost = (status.get("total_spent", 0) / max(status.get("call_count", 1), 1))
        spent_week = round(calls_week * avg_cost, 4)
        spent_month = round(calls_month * avg_cost, 4)
        conn.close()
    except Exception:
        pass

    # Daily usage for chart (last 14 days)
    daily_usage = []
    try:
        conn = sqlite3.connect(tool_usage_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT date(last_used) as day, SUM(count) as calls
               FROM tool_usage WHERE api_key = ? AND last_used >= datetime('now', '-14 days')
               GROUP BY date(last_used) ORDER BY day""",
            (api_key,),
        ).fetchall()
        daily_usage = [{"date": r["day"], "calls": r["calls"]} for r in rows]
        conn.close()
    except Exception:
        pass

    # Streak from engagement.db
    streak_days = 0
    try:
        eng_db = os.path.join(base_dir, "engagement.db")
        conn = sqlite3.connect(eng_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT current_streak, longest_streak FROM streaks WHERE user_id = ?", (api_key,)).fetchone()
        if row:
            streak_days = row["current_streak"]
        conn.close()
    except Exception:
        pass

    # Favorites from engagement.db
    favorite_tools = []
    try:
        eng_db = os.path.join(base_dir, "engagement.db")
        conn = sqlite3.connect(eng_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT item_slug FROM favorites WHERE user_id = ? AND item_type = 'tool' ORDER BY created_at DESC LIMIT 10", (api_key,)).fetchall()
        favorite_tools = [r["item_slug"] for r in rows]
        conn.close()
    except Exception:
        pass

    return {
        "key": api_key[:8] + "..." + api_key[-4:],
        "key_full": api_key,
        "balance_usd": status.get("balance_usd", 0),
        "total_spent": status.get("total_spent", 0),
        "total_calls": status.get("call_count", 0),
        "calls_today": calls_today,
        "top_tools": top_tools,
        "recent": recent,
        "created_at": status.get("created_at", ""),
        "last_used_at": status.get("last_used_at", ""),
        "is_active": status.get("is_active", 1),
        "label": status.get("label", ""),
        "referral_code": status.get("referral_code", ""),
        "calls_week": calls_week,
        "calls_month": calls_month,
        "calls_90d": calls_90d,
        "spent_week": spent_week,
        "spent_month": spent_month,
        "daily_usage": daily_usage,
        "streak_days": streak_days,
        "favorite_tools": favorite_tools,
    }


@auth_bp.route("/api/usage", methods=["GET"])
def api_usage():
    """JSON usage data for an API key. ?key=APK_xxx or Authorization header."""
    api_key = request.args.get("key", "")
    if not api_key:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            api_key = auth[7:]
    if not api_key or not api_key.startswith("apk_"):
        return jsonify({"error": "Valid API key required (query param ?key= or Authorization header)"}), 401
    data = _get_usage_data(api_key)
    if not data:
        return jsonify({"error": "key_not_found"}), 404
    # Return masked key in JSON response
    return jsonify({
        "key": data["key"],
        "balance_usd": data["balance_usd"],
        "total_calls": data["total_calls"],
        "calls_today": data["calls_today"],
        "calls_week": data["calls_week"],
        "calls_month": data["calls_month"],
        "calls_90d": data["calls_90d"],
        "spent_week": data["spent_week"],
        "spent_month": data["spent_month"],
        "daily_usage": data["daily_usage"],
        "streak_days": data["streak_days"],
        "favorite_tools": data["favorite_tools"],
        "top_tools": data["top_tools"],
        "created_at": data["created_at"],
    })


@auth_bp.route("/dashboard", methods=["GET"])
def usage_dashboard():
    """Self-serve usage dashboard. Accepts ?key=APK_xxx."""
    api_key = request.args.get("key", "")
    if not api_key or not api_key.startswith("apk_"):
        return render_template("dashboard.html", error="Enter your API key to view usage.", data=None)
    data = _get_usage_data(api_key)
    if not data:
        return render_template("dashboard.html", error="API key not found.", data=None)
    return render_template("dashboard.html", error=None, data=data)


@auth_bp.route("/usage/export", methods=["GET"])
def usage_export_csv():
    """Export API usage as CSV. Requires ?key=apk_xxx."""
    import csv, io
    api_key = request.args.get("key", "")
    if not api_key or not api_key.startswith("apk_"):
        return jsonify({"error": "API key required (?key=apk_xxx)"}), 400
    data = _get_usage_data(api_key)
    if not data:
        return jsonify({"error": "API key not found"}), 404

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["metric", "value"])
    writer.writerow(["api_key", api_key[:12] + "..."])
    writer.writerow(["balance_usd", data.get("balance", 0)])
    writer.writerow(["total_calls", data.get("call_count", 0)])
    writer.writerow(["total_spent", data.get("total_spent", 0)])
    writer.writerow(["spent_today", data.get("spent_today", 0)])
    writer.writerow(["spent_week", data.get("spent_week", 0)])
    writer.writerow(["spent_month", data.get("spent_month", 0)])
    writer.writerow(["streak_days", data.get("streak_days", 0)])
    writer.writerow(["created_at", data.get("created_at", "")])
    writer.writerow([])
    writer.writerow(["tool", "calls"])
    for tool in data.get("top_tools", []):
        writer.writerow([tool.get("tool", ""), tool.get("count", 0)])

    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = f"attachment; filename=aipaygen-usage-{api_key[:12]}.csv"
    return resp
