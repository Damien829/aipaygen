"""AiPayGen accounts blueprint — magic link auth, dashboard, key recovery."""

import os
import re
import time
from datetime import datetime, timezone
from functools import wraps

import jwt
from flask import Blueprint, request, jsonify, redirect, make_response

from accounts import (
    create_or_get_account, get_account_by_email, link_key_to_account,
    get_account_keys, update_last_login, set_digest_opt_out,
)
from email_service import send_magic_link

accounts_bp = Blueprint("accounts", __name__)

JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("ADMIN_SECRET") or os.urandom(32).hex()
BASE_URL = os.getenv("BASE_URL", "https://api.aipaygen.com")


def _create_token(email: str, expires_in: int = 900, token_type: str = "magic_link") -> str:
    return jwt.encode(
        {"email": email, "type": token_type, "exp": time.time() + expires_in, "iat": time.time()},
        JWT_SECRET, algorithm="HS256",
    )


def _get_current_account():
    token = request.cookies.get("session_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != "session":
            return None
        return get_account_by_email(payload["email"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


# ── Magic Link Auth ───────────────────────────────────────────────────────────

@accounts_bp.route("/auth/magic-link", methods=["POST"])
def magic_link():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Valid email required"}), 400
    token = _create_token(email, expires_in=900, token_type="magic_link")
    link = f"{BASE_URL}/auth/verify?token={token}"
    send_magic_link(email, link)
    return jsonify({"message": "Check your email for a sign-in link."})


@accounts_bp.route("/auth/verify", methods=["GET"])
def verify():
    token = request.args.get("token", "")
    if not token:
        return "Missing token", 400
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != "magic_link":
            return "Invalid token type", 400
    except jwt.ExpiredSignatureError:
        return "Link expired. Please request a new one.", 400
    except jwt.InvalidTokenError:
        return "Invalid token", 400
    email = payload["email"]
    acct = create_or_get_account(email)
    update_last_login(acct["id"])
    session_token = _create_token(email, expires_in=86400, token_type="session")
    resp = make_response(redirect("/dashboard"))
    resp.set_cookie("session_token", session_token, max_age=86400, httponly=True,
                     secure=True, samesite="Lax")
    return resp


# ── Login Page ────────────────────────────────────────────────────────────────

_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Sign In — AiPayGen</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0a0a;color:#e8e8e8;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.card{background:#141414;border:1px solid #2a2a2a;border-radius:16px;padding:40px;max-width:420px;width:100%;text-align:center}
h1{font-size:1.5rem;margin-bottom:8px}
.sub{color:#888;margin-bottom:24px}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #2a2a2a;background:#1e1e1e;color:#e8e8e8;font-size:1rem;margin-bottom:16px}
button{width:100%;padding:12px;border-radius:10px;border:none;background:#6366f1;color:#fff;font-size:1rem;font-weight:600;cursor:pointer}
button:hover{background:#818cf8}
.msg{margin-top:16px;color:#34d399;display:none}
.links{margin-top:20px;font-size:0.85rem}
.links a{color:#6366f1;text-decoration:none}
</style></head><body>
<div class="card">
  <h1>Sign In</h1>
  <p class="sub">Enter your email to receive a magic link.</p>
  <form id="f" onsubmit="return go()">
    <input id="email" type="email" placeholder="you@example.com" required>
    <button type="submit">Send Magic Link</button>
  </form>
  <p class="msg" id="msg">Check your email for a sign-in link.</p>
  <div class="links"><a href="/my-key">Recover API Key</a> &middot; <a href="/">Home</a></div>
</div>
<script>
async function go(){
  event.preventDefault();
  const r=await fetch('/auth/magic-link',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value})});
  if(r.ok){document.getElementById('msg').style.display='block';document.getElementById('f').style.display='none';}
  return false;
}
</script></body></html>"""

@accounts_bp.route("/auth/login", methods=["GET"])
def login_page():
    return _LOGIN_PAGE, 200, {"Content-Type": "text/html"}


# ── Key Recovery ──────────────────────────────────────────────────────────────

_KEY_RECOVERY_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Recover API Key — AiPayGen</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0a0a;color:#e8e8e8;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.card{background:#141414;border:1px solid #2a2a2a;border-radius:16px;padding:40px;max-width:420px;width:100%;text-align:center}
h1{font-size:1.5rem;margin-bottom:8px}
.sub{color:#888;margin-bottom:24px}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #2a2a2a;background:#1e1e1e;color:#e8e8e8;font-size:1rem;margin-bottom:16px}
button{width:100%;padding:12px;border-radius:10px;border:none;background:#6366f1;color:#fff;font-size:1rem;font-weight:600;cursor:pointer}
.msg{margin-top:16px;color:#34d399}
.links{margin-top:20px;font-size:0.85rem}
.links a{color:#6366f1;text-decoration:none}
</style></head><body>
<div class="card">
  <h1>Recover API Key</h1>
  <p class="sub">Enter the email used at purchase. We'll send a sign-in link to view your keys.</p>
  <form id="f" onsubmit="return go()">
    <input id="email" type="email" placeholder="you@example.com" required>
    <button type="submit">Look Up</button>
  </form>
  <p class="msg" id="msg" style="display:none"></p>
  <div class="links"><a href="/auth/login">Sign In</a> &middot; <a href="/">Home</a></div>
</div>
<script>
async function go(){
  event.preventDefault();
  const r=await fetch('/auth/key-lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value})});
  const d=await r.json();
  const m=document.getElementById('msg');m.style.display='block';m.textContent=d.message;
  return false;
}
</script></body></html>"""

@accounts_bp.route("/my-key", methods=["GET"])
def key_recovery_page():
    return _KEY_RECOVERY_PAGE, 200, {"Content-Type": "text/html"}


@accounts_bp.route("/auth/key-lookup", methods=["POST"])
def key_lookup():
    # Always return same message to prevent email enumeration
    msg = "If an account exists for that email, a sign-in link has been sent. Check your inbox."
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"message": msg})
    acct = _get_current_account()
    if acct and acct["email"] == email:
        keys = get_account_keys(acct["id"])
        from api_keys import get_key_status
        key_list = []
        for k in keys:
            status = get_key_status(k["api_key"])
            key_list.append({
                "api_key": k["api_key"],
                "balance": status["balance_usd"] if status else 0,
                "calls": status.get("total_calls", 0) if status else 0,
            })
        return jsonify({"keys": key_list, "message": f"Found {len(key_list)} key(s)."})
    # Not authenticated — send magic link
    existing = get_account_by_email(email)
    if existing:
        token = _create_token(email, expires_in=900, token_type="magic_link")
        link = f"{BASE_URL}/auth/verify?token={token}"
        send_magic_link(email, link)
    return jsonify({"message": msg})


# ── Dashboard ─────────────────────────────────────────────────────────────────

@accounts_bp.route("/dashboard", methods=["GET"])
def dashboard():
    acct = _get_current_account()
    if not acct:
        return redirect("/auth/login")
    from api_keys import get_key_status
    keys = get_account_keys(acct["id"])
    total_balance = 0.0
    total_calls = 0
    key_rows = ""
    for k in keys:
        status = get_key_status(k["api_key"])
        bal = status["balance_usd"] if status else 0
        calls = status.get("total_calls", 0) if status else 0
        total_balance += bal
        total_calls += calls
        truncated = k["api_key"][:8] + "..." + k["api_key"][-4:]
        key_rows += f'<tr><td style="padding:8px;font-family:monospace;cursor:pointer;" class="copyable" data-key="{k["api_key"]}">{truncated}</td><td style="padding:8px;color:#34d399;">${bal:.2f}</td><td style="padding:8px;">{calls}</td></tr>'
    if not key_rows:
        key_rows = '<tr><td colspan="3" style="padding:8px;color:#888;">No API keys linked yet.</td></tr>'
    email_safe = acct["email"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Dashboard — AiPayGen</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0a0a;color:#e8e8e8;min-height:100vh;padding:40px 24px}}
.wrap{{max-width:640px;margin:0 auto}}
h1{{font-size:1.6rem;margin-bottom:8px}}
.sub{{color:#888;margin-bottom:28px}}
.stats{{display:flex;gap:16px;margin-bottom:28px}}
.stat{{flex:1;background:#141414;border:1px solid #2a2a2a;border-radius:12px;padding:20px;text-align:center}}
.stat .val{{font-size:1.4rem;font-weight:700;color:#34d399}}
.stat .lbl{{font-size:0.8rem;color:#888;margin-top:4px}}
table{{width:100%;border-collapse:collapse;background:#141414;border:1px solid #2a2a2a;border-radius:12px;overflow:hidden;margin-bottom:24px}}
th{{padding:10px 8px;background:#1a1a1a;color:#888;font-size:0.8rem;text-align:left}}
.btn{{display:inline-block;background:#6366f1;color:#fff;text-decoration:none;border-radius:10px;padding:12px 24px;font-weight:600;margin-right:12px}}
.copy-toast{{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#34d399;color:#000;padding:8px 20px;border-radius:8px;display:none;font-weight:600}}
.nav{{margin-bottom:28px;font-size:0.9rem}}
.nav a{{color:#6366f1;text-decoration:none;margin-right:16px}}
</style></head><body>
<div class="wrap">
  <div class="nav"><a href="/">Home</a><a href="/docs">Docs</a><a href="/buy-credits">Buy Credits</a></div>
  <h1>Dashboard</h1>
  <p class="sub" id="email"></p>
  <div class="stats">
    <div class="stat"><div class="val">${total_balance:.2f}</div><div class="lbl">Balance</div></div>
    <div class="stat"><div class="val">{total_calls}</div><div class="lbl">API Calls</div></div>
  </div>
  <table>
    <thead><tr><th>API Key</th><th>Balance</th><th>Calls</th></tr></thead>
    <tbody>{key_rows}</tbody>
  </table>
  <a href="/buy-credits" class="btn">Top Up</a>
  <a href="/auth/login" class="btn" style="background:#2a2a2a;">Sign Out</a>
</div>
<div class="copy-toast" id="toast">Copied!</div>
<script>
document.getElementById('email').textContent = {repr(email_safe)};
document.querySelectorAll('.copyable').forEach(el=>{{
  el.addEventListener('click',()=>{{
    navigator.clipboard.writeText(el.dataset.key);
    const t=document.getElementById('toast');t.style.display='block';setTimeout(()=>t.style.display='none',1500);
  }});
}});
</script></body></html>"""
    return html, 200, {"Content-Type": "text/html"}


# ── Unsubscribe ───────────────────────────────────────────────────────────────

@accounts_bp.route("/unsubscribe", methods=["GET"])
def unsubscribe():
    email = (request.args.get("email") or "").strip().lower()
    if email:
        acct = get_account_by_email(email)
        if acct:
            set_digest_opt_out(acct["id"], True)
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Unsubscribed</title>
<style>body{font-family:sans-serif;background:#0a0a0a;color:#e8e8e8;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#141414;border:1px solid #2a2a2a;border-radius:16px;padding:40px;text-align:center;max-width:400px}</style></head>
<body><div class="card"><h2>Unsubscribed</h2><p style="color:#888;margin-top:12px;">You won't receive weekly digests anymore.</p>
<a href="/" style="color:#6366f1;display:block;margin-top:20px;">Back to Home</a></div></body></html>""", 200, {"Content-Type": "text/html"}
