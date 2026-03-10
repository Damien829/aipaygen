"""AiPayGen transactional email service via Resend."""

import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = "AiPayGen <noreply@aipaygen.com>"


def send_api_key_email(to: str, api_key: str, balance: float) -> bool:
    if not api_key:
        return False
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": "Your AiPayGen API Key",
            "html": f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0a0a;color:#e8e8e8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:520px;margin:40px auto;background:#141414;border:1px solid #2a2a2a;border-radius:16px;padding:40px;">
  <h1 style="font-size:1.5rem;margin-bottom:8px;">Your API Key is Ready</h1>
  <p style="color:#888;margin-bottom:24px;">Thanks for purchasing AiPayGen credits.</p>
  <div style="background:#1e1e1e;border:1px solid #2a2a2a;border-radius:10px;padding:16px;margin-bottom:20px;">
    <div style="font-size:0.8rem;color:#888;margin-bottom:6px;">API KEY</div>
    <div style="font-family:monospace;font-size:0.95rem;color:#a78bfa;word-break:break-all;">{api_key}</div>
  </div>
  <p style="font-size:1.1rem;margin-bottom:20px;">Balance: <span style="color:#34d399;font-weight:700;">${balance:.2f}</span></p>
  <div style="background:#1a1a1a;border-radius:8px;padding:14px;font-size:0.8rem;color:#888;margin-bottom:20px;">
    <pre style="margin:0;white-space:pre-wrap;">curl https://api.aipaygen.com/research \\
  -H "Authorization: Bearer {api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"topic": "quantum computing"}}'</pre>
  </div>
  <a href="https://aipaygen.com/docs" style="display:inline-block;background:#6366f1;color:#fff;text-decoration:none;border-radius:10px;padding:12px 24px;font-weight:600;">View Docs</a>
</div>
</body></html>"""
        })
        return True
    except Exception:
        return False


def send_free_tier_nudge(to: str, tools_used: int = 0, calls_made: int = 0) -> bool:
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": "You've used your free AiPayGen calls",
            "html": f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0a0a;color:#e8e8e8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:520px;margin:40px auto;background:#141414;border:1px solid #2a2a2a;border-radius:16px;padding:40px;">
  <h1 style="font-size:1.5rem;margin-bottom:8px;">Free Tier Exhausted</h1>
  <p style="color:#888;margin-bottom:24px;">You made {calls_made} calls across {tools_used} tools. Upgrade to keep going.</p>
  <p style="margin-bottom:24px;">Plans start at <span style="color:#34d399;font-weight:700;">$1</span> for ~100 API calls.</p>
  <a href="https://aipaygen.com/buy-credits" style="display:inline-block;background:#6366f1;color:#fff;text-decoration:none;border-radius:10px;padding:12px 24px;font-weight:600;">Buy Credits</a>
</div>
</body></html>"""
        })
        return True
    except Exception:
        return False


def send_magic_link(to: str, link: str) -> bool:
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": "Sign in to AiPayGen",
            "html": f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0a0a;color:#e8e8e8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:520px;margin:40px auto;background:#141414;border:1px solid #2a2a2a;border-radius:16px;padding:40px;">
  <h1 style="font-size:1.5rem;margin-bottom:8px;">Sign In</h1>
  <p style="color:#888;margin-bottom:24px;">Click the button below to verify your email and sign in. This link expires in 15 minutes.</p>
  <a href="{link}" style="display:inline-block;background:#6366f1;color:#fff;text-decoration:none;border-radius:10px;padding:12px 24px;font-weight:600;">Verify &amp; Sign In</a>
  <p style="color:#555;font-size:0.8rem;margin-top:24px;">If you didn't request this, ignore this email.</p>
</div>
</body></html>"""
        })
        return True
    except Exception:
        return False


def send_deposit_confirmation(api_key: str, amount: float, network: str, tx_hash: str) -> bool:
    """Send deposit confirmation email (if account has email on file)."""
    try:
        import sqlite3
        accounts_db = os.path.join(os.path.dirname(__file__), "accounts.db")
        conn = sqlite3.connect(accounts_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT email FROM accounts WHERE api_key = ?", (api_key,)).fetchone()
        conn.close()
        if not row or not row["email"]:
            return False
        email = row["email"]
        explorer = "https://basescan.org/tx/" if network == "base" else "https://solscan.io/tx/"
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [email],
            "subject": f"Deposit Confirmed — ${amount:.2f} USDC",
            "html": f'<!DOCTYPE html><html><body style="margin:0;padding:0;background:#0a0a0a;color:#e8e8e8;font-family:-apple-system,sans-serif;"><div style="max-width:520px;margin:40px auto;background:#141414;border:1px solid #2a2a2a;border-radius:16px;padding:40px;"><h1 style="font-size:1.5rem;">Deposit Confirmed</h1><p style="color:#888;">Your USDC deposit has been verified and credited.</p><p style="font-size:1.3rem;color:#34d399;font-weight:700;">${amount:.2f} USDC</p><p style="font-size:0.85rem;color:#888;">Network: {network.title()} — <a href="{explorer}{tx_hash}" style="color:#6366f1;">View Transaction</a></p></div></body></html>'
        })
        return True
    except Exception:
        return False


def send_weekly_digest(to: str, calls: int = 0, top_tools: list = None, spent: float = 0.0) -> bool:
    top_tools = top_tools or []
    tools_html = ", ".join(top_tools) if top_tools else "None"
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": "Your AiPayGen Weekly Summary",
            "html": f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0a0a;color:#e8e8e8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:520px;margin:40px auto;background:#141414;border:1px solid #2a2a2a;border-radius:16px;padding:40px;">
  <h1 style="font-size:1.5rem;margin-bottom:16px;">Weekly Summary</h1>
  <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
    <tr><td style="padding:8px 0;color:#888;">API Calls</td><td style="padding:8px 0;text-align:right;font-weight:700;">{calls}</td></tr>
    <tr><td style="padding:8px 0;color:#888;">Top Tools</td><td style="padding:8px 0;text-align:right;">{tools_html}</td></tr>
    <tr><td style="padding:8px 0;color:#888;">Spent</td><td style="padding:8px 0;text-align:right;color:#34d399;font-weight:700;">${spent:.2f}</td></tr>
  </table>
  <a href="https://aipaygen.com/dashboard" style="display:inline-block;background:#6366f1;color:#fff;text-decoration:none;border-radius:10px;padding:12px 24px;font-weight:600;">View Dashboard</a>
  <p style="color:#555;font-size:0.75rem;margin-top:24px;"><a href="https://aipaygen.com/unsubscribe?email={to}" style="color:#555;">Unsubscribe from weekly digests</a></p>
</div>
</body></html>"""
        })
        return True
    except Exception:
        return False
