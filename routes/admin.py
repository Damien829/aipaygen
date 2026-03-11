"""
Admin, discovery management, referral, blog, economy, self-test, health history,
costs, and miscellaneous admin endpoints — extracted from app.py as a Blueprint.
"""

import os
import re as _re
import json
import base64
import requests as _requests
from datetime import datetime
from flask import Blueprint, request, jsonify, Response

from helpers import (
    cache_get as _cache_get,
    cache_set as _cache_set,
    get_client_ip as _get_client_ip,
    log_payment,
    parse_json_from_claude,
    agent_response,
    require_admin,
    require_api_key,
)
from discovery_engine import (
    get_blog_post, list_blog_posts,
    generate_all_blog_posts, get_outreach_log,
    run_hourly, run_daily, run_weekly,
    run_canary, get_health_history,
    run_maintenance,
    track_cost, get_daily_cost, is_cost_throttled,
)
from referral import (
    register_referral_agent, record_click,
    get_referral_stats, get_referral_leaderboard,
)
from funnel_tracker import get_funnel_stats
from async_jobs import submit_job, get_job, run_job_async
from file_storage import save_file, get_file, delete_file, list_files
from webhook_relay import (
    create_webhook, receive_webhook_event,
    get_webhook_events, list_webhooks, get_webhook,
)
from agent_network import (
    add_knowledge, search_knowledge, get_trending_topics,
    submit_task, browse_tasks, claim_task, complete_task,
    get_free_tier_status, get_reputation, get_leaderboard,
    subscribe_tasks, get_task_subscribers,
)

admin_bp = Blueprint("admin", __name__)

# ── Module-level references set by init_admin_bp() ──────────────────────────
claude = None
call_model = None
parse_json = None

PAYMENTS_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "payments.jsonl")
DAILY_COST_LIMIT_USD = float(os.getenv("DAILY_COST_LIMIT_USD", "10.0"))
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_THROTTLE_MODEL = "claude-haiku-4-5-20251001"

INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "aipaygen2026indexnow")
DEVTO_API_KEY = os.getenv("DEVTO_API_KEY", "")


def _get_model(preferred: str = None) -> str:
    """Return the model to use. Falls back to haiku if daily cost exceeded."""
    if is_cost_throttled(DAILY_COST_LIMIT_USD):
        return _THROTTLE_MODEL
    return preferred or _DEFAULT_MODEL


def init_admin_bp(claude_client, call_model_fn, parse_json_fn):
    """Inject shared dependencies from app.py."""
    global claude, call_model, parse_json
    claude = claude_client
    call_model = call_model_fn
    parse_json = parse_json_fn


# ══════════════════════════════════════════════════════════════════════════════
# STATS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/stats")
@require_admin
def stats():
    if not os.path.exists(PAYMENTS_LOG):
        return jsonify({"total_requests": 0, "total_earned_usd": 0.0, "by_endpoint": {}})
    entries = []
    with open(PAYMENTS_LOG) as f:
        for line in f:
            entries.append(json.loads(line))
    by_endpoint = {}
    for e in entries:
        ep = e["endpoint"]
        by_endpoint.setdefault(ep, {"requests": 0, "earned_usd": 0.0})
        by_endpoint[ep]["requests"] += 1
        by_endpoint[ep]["earned_usd"] += e["amount_usd"]
    return jsonify({
        "total_requests": len(entries),
        "total_earned_usd": round(sum(e["amount_usd"] for e in entries), 4),
        "by_endpoint": by_endpoint,
    })


# ══════════════════════════════════════════════════════════════════════════════
# FUNNEL DASHBOARD — Visual conversion funnel analytics
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/admin/manifest.json")
def admin_manifest():
    return jsonify({
        "name": "AiPayGen Dashboard",
        "short_name": "AiPayGen",
        "description": "Conversion funnel & checkout alerts",
        "start_url": "/admin/funnel",
        "display": "standalone",
        "background_color": "#0a0a0a",
        "theme_color": "#6366f1",
        "icons": [
            {"src": "/admin/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/admin/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    })


@admin_bp.route("/admin/icon-192.png")
@admin_bp.route("/admin/icon-512.png")
def admin_icon():
    """Generate a simple SVG-based PNG icon."""
    size = 512 if "512" in request.path else 192
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">
      <rect width="{size}" height="{size}" rx="{size//8}" fill="#6366f1"/>
      <text x="50%" y="54%" font-family="Arial,sans-serif" font-size="{size//3}" font-weight="800"
            fill="white" text-anchor="middle" dominant-baseline="middle">AP</text>
    </svg>'''
    return svg, 200, {"Content-Type": "image/svg+xml"}


@admin_bp.route("/admin/sw.js")
def admin_sw():
    return "self.addEventListener('fetch', e => e.respondWith(fetch(e.request)));", 200, {"Content-Type": "application/javascript"}


@admin_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Simple admin login page — sets session cookie."""
    from flask import session, redirect
    if request.method == "POST":
        key = request.form.get("key", "")
        admin_secret = os.getenv("ADMIN_SECRET", "")
        if key == admin_secret:
            session["admin"] = True
            return redirect("/admin/funnel")
        return """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Admin Login</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,sans-serif;background:#0a0a0a;color:#e8e8e8;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}.card{background:#141414;border:1px solid #2a2a2a;border-radius:14px;padding:32px;max-width:380px;width:100%}h1{font-size:1.3rem;margin-bottom:16px}input{width:100%;background:#1e1e1e;border:1px solid #2a2a2a;border-radius:8px;padding:10px 14px;color:#e8e8e8;font-size:0.9rem;margin-bottom:12px}button{width:100%;background:#6366f1;color:#fff;border:none;border-radius:8px;padding:12px;font-size:0.95rem;font-weight:600;cursor:pointer}.err{color:#f87171;font-size:0.85rem;margin-bottom:12px}</style></head><body>
<div class="card"><h1>Admin Login</h1><p class="err">Invalid key</p><form method="POST"><input type="password" name="key" placeholder="Admin key" autofocus><button type="submit">Login</button></form></div></body></html>""", 401, {"Content-Type": "text/html"}
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Admin Login</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,sans-serif;background:#0a0a0a;color:#e8e8e8;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}.card{background:#141414;border:1px solid #2a2a2a;border-radius:14px;padding:32px;max-width:380px;width:100%}h1{font-size:1.3rem;margin-bottom:16px}input{width:100%;background:#1e1e1e;border:1px solid #2a2a2a;border-radius:8px;padding:10px 14px;color:#e8e8e8;font-size:0.9rem;margin-bottom:12px}button{width:100%;background:#6366f1;color:#fff;border:none;border-radius:8px;padding:12px;font-size:0.95rem;font-weight:600;cursor:pointer}</style></head><body>
<div class="card"><h1>Admin Login</h1><form method="POST"><input type="password" name="key" placeholder="Admin key" autofocus><button type="submit">Login</button></form></div></body></html>""", 200, {"Content-Type": "text/html"}


@admin_bp.route("/admin/funnel")
def funnel_dashboard():
    """Funnel dashboard — requires admin session, query key, or header key."""
    from flask import session, redirect
    admin_secret = os.getenv("ADMIN_SECRET", "")
    # Check session cookie
    if session.get("admin"):
        pass  # authenticated
    # Check query param or header
    elif request.form.get("key") == admin_secret:
        session["admin"] = True  # set cookie for future visits
    elif request.headers.get("X-Admin-Key") == admin_secret:
        pass
    elif request.headers.get("Authorization", "").replace("Bearer ", "") == admin_secret:
        pass
    else:
        return redirect("/admin/login")
    days = int(request.args.get("days", 7))
    stats = get_funnel_stats(days)
    by_type = stats.get("by_type", {})

    # Read checkout alerts
    alert_log = os.path.join(os.path.dirname(os.path.dirname(__file__)), "checkout_alerts.log")
    alerts_html = ""
    try:
        with open(alert_log) as f:
            lines = f.readlines()[-20:]  # last 20
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            is_paid = "PAID" in line
            color = "#059669" if is_paid else "#f59e0b"
            icon = "&#10003;" if is_paid else "&#9888;"
            alerts_html += f'<div class="alert-row" style="border-left:3px solid {color}"><span style="color:{color}">{icon}</span> {line}</div>'
    except FileNotFoundError:
        alerts_html = '<div class="alert-row" style="color:#555">No checkout attempts yet</div>'

    # Funnel stages in order
    stages = [
        ("discover_hit", "Discover Page", "#6366f1"),
        ("llms_txt_hit", "LLMs.txt", "#818cf8"),
        ("demo_used", "Demo Used", "#34d399"),
        ("402_shown", "Payment Wall (402)", "#f59e0b"),
        ("checkout_started", "Checkout Started", "#f97316"),
        ("credits_bought", "Credits Bought", "#059669"),
        ("key_generated", "Key Generated", "#10b981"),
    ]

    max_val = max((by_type.get(s[0], 0) for s in stages), default=1) or 1

    bars_html = ""
    for event_type, label, color in stages:
        count = by_type.get(event_type, 0)
        pct = round((count / max_val) * 100)
        bars_html += f'''
        <div class="funnel-row">
          <div class="funnel-label">{label}</div>
          <div class="funnel-bar-wrap">
            <div class="funnel-bar" style="width:{pct}%;background:{color}">{count}</div>
          </div>
        </div>'''

    # Daily breakdown table
    daily = stats.get("daily", [])
    daily_rows = ""
    for d in daily:
        daily_rows += f'<tr><td>{d["day"]}</td><td>{d["event_type"]}</td><td>{d["count"]}</td></tr>'

    # Other events not in the funnel
    other_events = {k: v for k, v in by_type.items() if k not in [s[0] for s in stages]}
    other_html = ""
    if other_events:
        other_html = '<h2>Other Events</h2><div class="other-grid">'
        for evt, cnt in sorted(other_events.items(), key=lambda x: -x[1]):
            other_html += f'<div class="other-card"><div class="other-count">{cnt}</div><div class="other-label">{evt}</div></div>'
        other_html += '</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Funnel Dashboard — AiPayGen</title>
<link rel="manifest" href="/admin/manifest.json">
<meta name="theme-color" content="#0a0a0a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="AiPayGen">
<link rel="apple-touch-icon" href="/admin/icon-192.png">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e8e8e8; padding: 32px 16px; }}
  .wrap {{ max-width: 800px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 4px; }}
  .sub {{ color: #888; font-size: 0.85rem; margin-bottom: 24px; }}
  .period {{ display: flex; gap: 8px; margin-bottom: 24px; }}
  .period a {{ padding: 6px 14px; border-radius: 6px; background: #1e1e1e; color: #888; text-decoration: none; font-size: 0.82rem; border: 1px solid #2a2a2a; }}
  .period a.active {{ background: #6366f1; color: #fff; border-color: #6366f1; }}
  .card {{ background: #141414; border: 1px solid #2a2a2a; border-radius: 14px; padding: 28px; margin-bottom: 20px; }}
  .funnel-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
  .funnel-label {{ min-width: 160px; font-size: 0.82rem; color: #aaa; text-align: right; }}
  .funnel-bar-wrap {{ flex: 1; background: #1a1a1a; border-radius: 6px; height: 32px; overflow: hidden; }}
  .funnel-bar {{ height: 100%; border-radius: 6px; display: flex; align-items: center; padding: 0 10px; font-size: 0.8rem; font-weight: 700; color: #fff; min-width: 30px; transition: width 0.4s; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .stat {{ background: #1a1a1a; border-radius: 10px; padding: 16px; text-align: center; }}
  .stat .num {{ font-size: 1.6rem; font-weight: 800; color: #6366f1; }}
  .stat .lbl {{ font-size: 0.75rem; color: #666; margin-top: 4px; }}
  h2 {{ font-size: 1.1rem; margin: 24px 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #222; }}
  th {{ color: #888; font-weight: 600; }}
  .other-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }}
  .other-card {{ background: #1a1a1a; border-radius: 8px; padding: 12px; text-align: center; }}
  .other-count {{ font-size: 1.2rem; font-weight: 700; color: #818cf8; }}
  .other-label {{ font-size: 0.72rem; color: #666; margin-top: 4px; word-break: break-all; }}
  .alert-row {{ background: #1a1a1a; border-radius: 6px; padding: 10px 14px; margin-bottom: 6px; font-size: 0.8rem; font-family: monospace; color: #ccc; display: flex; align-items: center; gap: 8px; }}
  .alerts-wrap {{ max-height: 300px; overflow-y: auto; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Conversion Funnel</h1>
  <p class="sub">Last {days} days &middot; {stats['total_events']} total events</p>

  <div class="period">
    <a href="?days=1" class="{'active' if days==1 else ''}">24h</a>
    <a href="?days=7" class="{'active' if days==7 else ''}">7d</a>
    <a href="?days=30" class="{'active' if days==30 else ''}">30d</a>
    <a href="?days=90" class="{'active' if days==90 else ''}">90d</a>
  </div>

  <div class="stat-grid">
    <div class="stat"><div class="num">{by_type.get('discover_hit', 0)}</div><div class="lbl">Discover Hits</div></div>
    <div class="stat"><div class="num">{by_type.get('demo_used', 0)}</div><div class="lbl">Demos Used</div></div>
    <div class="stat"><div class="num">{by_type.get('402_shown', 0)}</div><div class="lbl">402s Shown</div></div>
    <div class="stat"><div class="num">{by_type.get('checkout_started', 0)}</div><div class="lbl">Checkouts</div></div>
    <div class="stat"><div class="num">{by_type.get('credits_bought', 0)}</div><div class="lbl">Purchases</div></div>
  </div>

  <div class="card">
    <h2 style="margin-top:0">Checkout Alerts</h2>
    <div class="alerts-wrap">{alerts_html}</div>
  </div>

  <div class="card">
    <h2 style="margin-top:0">Funnel</h2>
    {bars_html}
  </div>

  {other_html}

  <div class="card">
    <h2 style="margin-top:0">Daily Breakdown</h2>
    <table>
      <thead><tr><th>Date</th><th>Event</th><th>Count</th></tr></thead>
      <tbody>{daily_rows if daily_rows else '<tr><td colspan="3" style="color:#555">No events yet</td></tr>'}</tbody>
    </table>
  </div>

  <p style="text-align:center;margin-top:20px;font-size:0.75rem;color:#444"><a href="/stats" style="color:#555">Payment stats</a> &middot; Auto-refreshes every 5m</p>
</div>
<script>
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/admin/sw.js');
setTimeout(() => location.reload(), 300000);
</script>
</body>
</html>""", 200, {"Content-Type": "text/html"}


# ══════════════════════════════════════════════════════════════════════════════
# BLOG — Auto-generated SEO tutorials, indexed by search engines + LLMs
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/blog", methods=["GET"])
def blog_index():
    from security import sanitize_html
    posts = list_blog_posts()
    items = "".join(
        f'<li style="margin:0.6rem 0"><a href="/blog/{sanitize_html(p["slug"])}">{sanitize_html(p["title"])}</a> <small style="color:#888">· {sanitize_html(p.get("generated_at","")[:10])}</small></li>'
        for p in posts
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AiPayGen Blog — AI Agent & API Developer Tutorials</title>
<meta name="description" content="Developer tutorials for building with AiPayGen — 155 tools and 140+ Claude-powered AI API endpoints. Covers AI agents, scraping, x402 payments, real-time data, and more. First 10 calls/day free.">
<link rel="canonical" href="https://api.aipaygen.com/blog">
<link rel="alternate" type="application/rss+xml" title="AiPayGen Blog RSS" href="/feed.xml">
<meta property="og:type" content="website">
<meta property="og:title" content="AiPayGen Developer Blog">
<meta property="og:description" content="Tutorials for building AI agents and automations with AiPayGen's 155 tools and 140+ Claude-powered endpoints.">
<meta property="og:url" content="https://api.aipaygen.com/blog">
<meta property="og:image" content="https://api.aipaygen.com/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps({"@context":"https://schema.org","@type":"Blog","name":"AiPayGen Developer Blog","url":"https://api.aipaygen.com/blog","description":"Developer tutorials for AI agent APIs","publisher":{"@type":"Organization","name":"AiPayGen","url":"https://api.aipaygen.com"}})}</script>
<style>body{{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6;color:#1a1a1a}}a{{color:#6366f1}}h1{{color:#1e1b4b}}.rss{{float:right;font-size:0.85rem;background:#f4f4f4;padding:4px 10px;border-radius:20px;text-decoration:none;color:#555}}</style>
</head>
<body>
<a class="rss" href="/feed.xml">RSS feed</a>
<h1>AiPayGen Developer Blog</h1>
<p>Tutorials for building AI agents with AiPayGen — 155 tools and 140+ Claude-powered endpoints. <strong>First 10 calls/day free.</strong></p>
<ul style="padding-left:1.2rem">{items}</ul>
<p><a href="https://api.aipaygen.com/discover">Browse all 155 tools and 140+ endpoints →</a> · <a href="https://api.aipaygen.com/buy-credits">Buy credits ($5+) →</a></p>
</body>
</html>"""
    resp = Response(html, content_type="text/html")
    resp.headers["Link"] = '</feed.xml>; rel="alternate"; type="application/rss+xml"'
    return resp


@admin_bp.route("/blog/<slug>", methods=["GET"])
def blog_post(slug):
    from security import sanitize_html
    post = get_blog_post(slug)
    if not post:
        return jsonify({"error": "post not found"}), 404
    # Sanitize title for use in HTML attributes and text (content is trusted AI-generated HTML)
    safe_title = sanitize_html(post['title'])
    canonical = f"https://api.aipaygen.com/blog/{sanitize_html(slug)}"
    desc = f"{safe_title} — Developer tutorial for AiPayGen, the pay-per-use Claude AI API with 155 tools and 140+ endpoints."
    jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "TechArticle",
        "headline": safe_title,
        "description": desc,
        "url": canonical,
        "datePublished": post.get("generated_at", "")[:10],
        "author": {"@type": "Organization", "name": "AiPayGen"},
        "publisher": {
            "@type": "Organization",
            "name": "AiPayGen",
            "url": "https://api.aipaygen.com"
        }
    })
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title} — AiPayGen</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="{safe_title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://api.aipaygen.com/og-image.png">
<meta property="og:site_name" content="AiPayGen">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{safe_title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="https://api.aipaygen.com/og-image.png">
<script type="application/ld+json">{jsonld}</script>
<style>
body{{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.7;color:#1a1a1a}}
code,pre{{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:0.9em;font-family:monospace}}
pre{{padding:16px;overflow-x:auto;display:block}}a{{color:#6366f1}}h1{{color:#1e1b4b;font-size:1.9rem}}
.nav{{color:#888;margin-bottom:2rem;font-size:0.9rem}}.cta{{background:#f8f7ff;border:1px solid #e0e0ff;border-radius:8px;padding:16px;margin:2rem 0}}
</style>
</head>
<body>
<div class="nav"><a href="/blog">← All posts</a> · <a href="https://api.aipaygen.com">AiPayGen API</a> · <a href="/discover">155 tools</a></div>
<h1>{safe_title}</h1>
{post['content']}
<div class="cta">
  <strong>Try it free →</strong> First 10 calls/day free, no credit card. <a href="https://api.aipaygen.com/discover">Browse all 155 tools and 140+ endpoints</a> or <a href="https://api.aipaygen.com/buy-credits">buy credits ($5+)</a>.
</div>
<p style="color:#888;font-size:0.85rem">Published: {post.get('generated_at','')[:10]} · <a href="/feed.xml">RSS feed</a></p>
</body>
</html>"""
    return Response(html, content_type="text/html")


# ══════════════════════════════════════════════════════════════════════════════
# REFERRAL / AFFILIATE PROGRAM
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/referral/join", methods=["POST"])
def referral_join():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "").strip()
    label = data.get("label", "")
    api_key = data.get("api_key", "")
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400
    result = register_referral_agent(agent_id, label, api_key)
    result["note"] = "Share your referral_url. Earn 10% of every purchase your referrals make, credited to your API key."
    return jsonify(result)


@admin_bp.route("/referral/stats/<agent_id>", methods=["GET"])
def referral_stats(agent_id):
    return jsonify(get_referral_stats(agent_id))


@admin_bp.route("/referral/leaderboard", methods=["GET"])
def referral_leaderboard():
    limit = min(int(request.args.get("limit", 20)), 100)
    return jsonify({"leaderboard": get_referral_leaderboard(limit), "commission_rate": "10%"})


@admin_bp.route("/ref/<agent_id>", methods=["GET"])
def referral_redirect(agent_id):
    """Short referral redirect — /ref/my-agent → home with ?ref=my-agent cookie set."""
    ip = _get_client_ip()
    try:
        record_click(agent_id, ip, "/ref/" + agent_id, request.headers.get("User-Agent", ""))
    except Exception:
        pass
    from security import validate_redirect_url
    dest = validate_redirect_url(request.args.get("to", "/buy-credits")) + f"?ref={agent_id}"
    from flask import redirect
    return redirect(dest, code=302)


# ══════════════════════════════════════════════════════════════════════════════
# DISCOVERY ENGINE — outreach status + manual trigger
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/discovery/status", methods=["GET"])
@require_admin
def discovery_engine_status():
    log = get_outreach_log(50)
    posts = list_blog_posts()
    return jsonify({"outreach_log": log, "blog_posts": len(posts), "posts": posts})


@admin_bp.route("/discovery/trigger", methods=["POST"])
@require_admin
def discovery_trigger():
    data = request.get_json() or {}
    job = data.get("job", data.get("task", "hourly"))
    import threading as _t
    if job == "daily":
        _t.Thread(target=lambda: run_daily(claude), daemon=True).start()
    elif job == "weekly":
        _t.Thread(target=lambda: run_weekly(claude), daemon=True).start()
    elif job == "blog":
        _t.Thread(target=lambda: generate_all_blog_posts(claude, force=True), daemon=True).start()
    elif job == "canary":
        result = run_canary()
        return jsonify({"job": "canary", "result": result})
    elif job == "maintenance":
        result = run_maintenance()
        return jsonify({"job": "maintenance", "result": result})
    elif job == "economy":
        _t.Thread(target=_run_agent_economy, daemon=True).start()
        return jsonify({"job": "economy", "note": "Running in background"})
    else:
        _t.Thread(target=lambda: run_hourly(claude), daemon=True).start()
    return jsonify({"triggered": job, "note": "Running in background"})


# ══════════════════════════════════════════════════════════════════════════════
# DISCOVERY SCOUTS — status, stats, manual trigger, weekly report
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/discovery/scouts/status", methods=["GET"])
@require_admin
def scouts_status():
    from discovery_scouts import get_scout_status
    return jsonify(get_scout_status())


@admin_bp.route("/discovery/scouts/stats", methods=["GET"])
@require_admin
def scouts_stats():
    from discovery_scouts import get_scout_stats
    return jsonify(get_scout_stats())


@admin_bp.route("/discovery/scouts/run/<scout_name>", methods=["POST"])
@require_admin
def scouts_run(scout_name):
    from discovery_scouts import run_scout_by_name
    if not _re.match(r'^[a-z_]+$', scout_name):
        return jsonify({"error": "Invalid scout name"}), 400
    result = run_scout_by_name(scout_name, call_model)
    if result is None:
        return jsonify({"error": f"Unknown scout: {scout_name}"}), 404
    return jsonify(result)


@admin_bp.route("/discovery/scouts/report", methods=["GET"])
@require_admin
def scouts_report():
    from discovery_scouts import get_weekly_report
    return jsonify(get_weekly_report())


@admin_bp.route("/discovery/scouts/absorbed", methods=["GET"])
@require_admin
def scouts_absorbed():
    from discovery_scouts import get_absorbed_skills_stats
    return jsonify(get_absorbed_skills_stats())


# ══════════════════════════════════════════════════════════════════════════════
# API HUNTER-GATHERER ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/admin/hunter", methods=["GET"])
@require_admin
def admin_hunter_stats():
    import sqlite3 as _sql
    from api_catalog import DB_PATH as _cat_db
    stats = {"total_cataloged": 0, "today": 0, "score_distribution": {}, "top_recent": [], "injected": 0}
    try:
        c = _sql.connect(_cat_db)
        c.row_factory = _sql.Row
        stats["total_cataloged"] = c.execute("SELECT COUNT(*) FROM discovered_apis").fetchone()[0]
        stats["today"] = c.execute(
            "SELECT COUNT(*) FROM discovered_apis WHERE created_at >= date('now')"
        ).fetchone()[0]
        for row in c.execute(
            "SELECT CASE WHEN quality_score >= 9 THEN '9-10' "
            "WHEN quality_score >= 7 THEN '7-8' "
            "WHEN quality_score >= 5 THEN '5-6' "
            "ELSE '0-4' END as bracket, COUNT(*) as cnt "
            "FROM discovered_apis GROUP BY bracket"
        ).fetchall():
            stats["score_distribution"][row["bracket"]] = row["cnt"]
        stats["top_recent"] = [dict(r) for r in c.execute(
            "SELECT name, base_url, category, quality_score, source, created_at "
            "FROM discovered_apis ORDER BY created_at DESC LIMIT 10"
        ).fetchall()]
        c.close()
    except Exception:
        pass
    try:
        from outbound_agent import DB_PATH as _out_db
        oc = _sql.connect(_out_db)
        stats["injected"] = oc.execute(
            "SELECT COUNT(*) FROM discovered_services WHERE source='api_hunter'"
        ).fetchone()[0]
        oc.close()
    except Exception:
        pass
    return jsonify(stats)


@admin_bp.route("/admin/hunter/run", methods=["POST"])
@require_admin
def admin_hunter_run():
    import threading
    from api_discovery import run_all_hunters, inject_high_scorers

    def _run_hunters():
        try:
            found = run_all_hunters(claude, max_per_run=200)
            injected = inject_high_scorers(min_score=7)
            import logging
            logging.getLogger(__name__).info(f"Hunter run complete: found={found}, injected={injected}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Hunter run failed: {e}")

    threading.Thread(target=_run_hunters, daemon=True).start()
    return jsonify({"status": "started", "message": "Hunter run started in background. Check /admin/hunter for results."})


@admin_bp.route("/admin/catalog-economics", methods=["GET"])
@require_admin
def catalog_economics():
    from api_catalog import get_catalog_economics
    return jsonify(get_catalog_economics())


@admin_bp.route("/admin/x402-spend", methods=["GET"])
@require_admin
def x402_spend():
    try:
        from x402_client import get_spend_stats
        return jsonify(get_spend_stats())
    except Exception as e:
        return jsonify({"error": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# FREE DAILY TIER STATUS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/free-tier/status", methods=["GET"])
def free_tier_status():
    ip = _get_client_ip()
    return jsonify(get_free_tier_status(ip))


# ══════════════════════════════════════════════════════════════════════════════
# AGENT REPUTATION + LEADERBOARD
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/agents/leaderboard", methods=["GET"])
def agents_leaderboard():
    limit = min(int(request.args.get("limit", 20)), 100)
    board = get_leaderboard(limit)
    return jsonify({"leaderboard": board, "count": len(board),
                    "scoring": "task_completions\u00d73 + knowledge_contributions\u00d71.5 + upvotes\u00d70.5"})


@admin_bp.route("/agent/reputation/<agent_id>", methods=["GET"])
def agent_reputation_route(agent_id):
    return jsonify(get_reputation(agent_id))


# ══════════════════════════════════════════════════════════════════════════════
# TASK SUBSCRIPTIONS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/task/subscribe", methods=["POST"])
@require_api_key
def task_subscribe():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "")
    callback_url = data.get("callback_url", "")
    skills = data.get("skills", [])
    if not agent_id or not callback_url:
        return jsonify({"error": "agent_id and callback_url required"}), 400
    result = subscribe_tasks(agent_id, skills, callback_url)
    return jsonify(result)


@admin_bp.route("/task/subscription/<agent_id>", methods=["GET"])
@require_api_key
def task_subscription_status(agent_id):
    sub = get_task_subscribers(agent_id)
    if not sub:
        return jsonify({"error": "no subscription found", "agent_id": agent_id}), 404
    return jsonify(sub)


# ══════════════════════════════════════════════════════════════════════════════
# ASYNC JOBS + WEBHOOK CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

# Mapping of endpoint name -> handler function (for async execution)
_ASYNC_HANDLERS = {}  # populated after route definitions (see bottom of routes section)


@admin_bp.route("/async/submit", methods=["POST"])
@require_admin
def async_submit():
    data = request.get_json() or {}
    endpoint = data.get("endpoint", "").lstrip("/")
    payload = data.get("payload", {})
    callback_url = data.get("callback_url")
    if not endpoint or not payload:
        return jsonify({"error": "endpoint and payload required"}), 400
    if endpoint not in _ASYNC_HANDLERS:
        available = list(_ASYNC_HANDLERS.keys())
        return jsonify({"error": "unsupported async endpoint", "available": available}), 400
    job_id = submit_job(endpoint, payload, callback_url)
    run_job_async(job_id, _ASYNC_HANDLERS[endpoint])
    return jsonify({
        "job_id": job_id,
        "status": "pending",
        "status_url": f"https://api.aipaygen.com/async/status/{job_id}",
        "callback_url": callback_url,
        "note": "Poll status_url or wait for callback POST",
    })


@admin_bp.route("/async/status/<job_id>", methods=["GET"])
@require_admin
def async_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


# ══════════════════════════════════════════════════════════════════════════════
# FILE STORAGE
# ══════════════════════════════════════════════════════════════════════════════

_ALLOWED_UPLOAD_MIMES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/bmp", "image/tiff",
    "text/plain", "text/csv", "text/markdown", "text/xml", "text/html",
    "application/json", "application/pdf", "application/xml",
    "application/x-yaml", "application/yaml", "text/yaml",
    "application/zip", "application/gzip", "application/x-tar",
    "application/x-gzip", "application/octet-stream",
}
_BLOCKED_UPLOAD_EXTS = {
    "exe", "bat", "cmd", "com", "dll", "msi", "ps1", "sh", "bash",
    "js", "vbs", "wsf", "scr", "pif", "reg", "inf", "hta", "cpl",
    "jar", "py", "rb", "pl", "php",
}

@admin_bp.route("/files/upload", methods=["POST"])
@require_api_key
def files_upload():
    agent_id = request.args.get("agent_id") or (request.get_json() or {}).get("agent_id", "anonymous")
    if "file" in request.files:
        f = request.files["file"]
        data = f.read()
        filename = f.filename or "upload"
        content_type = f.content_type or "application/octet-stream"
    else:
        body = request.get_json() or {}
        b64 = body.get("base64_data", "")
        filename = body.get("filename", "file.bin")
        content_type = body.get("content_type", "application/octet-stream")
        try:
            data = base64.b64decode(b64)
        except Exception:
            return jsonify({"error": "invalid base64_data"}), 400
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _BLOCKED_UPLOAD_EXTS:
        return jsonify({"error": f"Blocked file extension: .{ext}"}), 400
    if content_type not in _ALLOWED_UPLOAD_MIMES:
        return jsonify({"error": f"Blocked content type: {content_type}"}), 400
    try:
        result = save_file(agent_id, filename, content_type, data)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 413


@admin_bp.route("/files/<file_id>", methods=["GET"])
@require_api_key
def files_get(file_id):
    meta, data = get_file(file_id)
    if meta is None:
        return jsonify({"error": "file not found"}), 404
    safe_filename = _re.sub(r'[^\w.\-]', '_', meta.get("filename", "file"))
    return Response(data, content_type=meta["content_type"],
                    headers={"Content-Disposition": f"attachment; filename=\"{safe_filename}\""})


@admin_bp.route("/files/<file_id>", methods=["DELETE"])
@require_api_key
def files_delete(file_id):
    agent_id = (request.get_json() or {}).get("agent_id", "")
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400
    ok = delete_file(file_id, agent_id)
    return jsonify({"deleted": ok, "file_id": file_id})


@admin_bp.route("/files/list/<agent_id>", methods=["GET"])
@require_api_key
def files_list(agent_id):
    files = list_files(agent_id)
    return jsonify({"files": files, "count": len(files), "agent_id": agent_id})


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK RELAY
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/webhooks/create", methods=["POST"])
@require_api_key
def webhooks_create():
    data = request.get_json() or {}
    agent_id = data.get("agent_id", "anonymous")
    label = data.get("label")
    result = create_webhook(agent_id, label)
    return jsonify(result)


@admin_bp.route("/webhooks/<webhook_id>/receive", methods=["GET", "POST", "PUT", "PATCH"])
def webhooks_receive(webhook_id):
    body = request.get_data(as_text=True)
    headers = dict(request.headers)
    ip = _get_client_ip()
    result = receive_webhook_event(webhook_id, request.method, headers, body, ip)
    if result is None:
        return jsonify({"error": "webhook not found"}), 404
    return jsonify({"received": True, "event_id": result["event_id"]})


@admin_bp.route("/webhooks/<webhook_id>/events", methods=["GET"])
@require_api_key
def webhooks_events(webhook_id):
    hook = get_webhook(webhook_id)
    if not hook:
        return jsonify({"error": "webhook not found"}), 404
    limit = min(int(request.args.get("limit", 50)), 200)
    events = get_webhook_events(webhook_id, limit)
    return jsonify({
        "webhook_id": webhook_id,
        "events": events,
        "count": len(events),
        "total_received": hook["event_count"],
    })


@admin_bp.route("/webhooks/list/<agent_id>", methods=["GET"])
@require_api_key
def webhooks_list(agent_id):
    hooks = list_webhooks(agent_id)
    return jsonify({"webhooks": hooks, "count": len(hooks)})


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN FUNNEL
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/admin/funnel")
@require_admin
def admin_funnel():
    """Conversion funnel stats. ?days=7 (default). Protected by ADMIN_SECRET."""
    days = request.args.get("days", 7, type=int)
    days = min(max(days, 1), 365)
    stats = get_funnel_stats(days=days)
    return jsonify(stats)


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST + HEALTH HISTORY
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/self-test", methods=["GET", "POST"])
def self_test():
    """Manually trigger canary probe and return results."""
    results = run_canary()
    return jsonify(results)


@admin_bp.route("/health/history", methods=["GET"])
def health_history():
    endpoint = request.args.get("endpoint")
    limit = int(request.args.get("limit", 100))
    return jsonify({"history": get_health_history(endpoint, limit)})


# ── Cost Tracking & Visibility ────────────────────────────────────────────────

@admin_bp.route("/costs", methods=["GET"])
def costs():
    """Show today's Claude API cost and throttle status."""
    today = get_daily_cost()
    throttled = is_cost_throttled(DAILY_COST_LIMIT_USD)
    return jsonify({
        "today": today,
        "daily_limit_usd": DAILY_COST_LIMIT_USD,
        "throttled": throttled,
        "model_in_use": _get_model(),
        "_meta": {"note": "Set DAILY_COST_LIMIT_USD env var to change limit (default $10)"},
    })


# ── Agent-to-Agent Economy ────────────────────────────────────────────────────

_economy_stats = {
    "tasks_auto_posted": 0,
    "tasks_auto_completed": 0,
    "knowledge_seeded": 0,
    "last_run": None,
}

# Topics the KnowledgeAgent seeds into the knowledge base automatically
_KNOWLEDGE_SEEDS = [
    {
        "topic": "aipaygen-api-reference",
        "content": (
            "AiPayGen API (https://api.aipaygen.com) has 155 tools and 140+ endpoints. "
            "Key endpoints: /research ($0.01), /write ($0.05), /analyze ($0.02), /code ($0.05), "
            "/scrape/google-maps ($0.10), /chain ($0.25 for 5-step pipelines), /rag ($0.05). "
            "Free tier: 10 calls/day per IP. Prepaid keys: /buy-credits. "
            "OpenAPI spec: /openapi.json. MCP tools: /sdk."
        ),
        "tags": ["api", "aipaygen", "reference"],
        "entry_id": "kb-aipaygen-api-ref-v1",
    },
    {
        "topic": "x402-payment-protocol",
        "content": (
            "x402 is a payment protocol for AI agents. HTTP 402 response includes payment details. "
            "Agents pay USDC on Base Mainnet. AiPayGen wallet: 0x366D488a48de1B2773F3a21F1A6972715056Cb30."
            "Facilitator: https://x402.org/facilitator. Use x402-python or x402-js SDK."
        ),
        "tags": ["x402", "payment", "usdc", "base"],
        "entry_id": "kb-x402-protocol-v1",
    },
    {
        "topic": "ai-agent-best-practices",
        "content": (
            "Best practices for AI agents: 1) Use idempotency keys (X-Idempotency-Key header). "
            "2) Cache free data endpoints (weather=600s, crypto=120s). "
            "3) Use /chain for multi-step pipelines instead of sequential calls. "
            "4) Store agent state with /memory/set. 5) Use /task/submit to delegate work. "
            "6) Monitor costs at /costs. 7) Subscribe to tasks at /task/subscribe."
        ),
        "tags": ["agents", "best-practices", "architecture"],
        "entry_id": "kb-agent-best-practices-v1",
    },
]

# Auto-tasks that specialist agents post to the task board periodically
_AUTO_TASKS = [
    {
        "posted_by": "agent-content-v1",
        "title": "Generate tutorial blog post for trending AI topic",
        "description": "Research current trending AI topics on HN and write a developer tutorial connecting it to AiPayGen endpoints. Post result to knowledge base.",
        "skills_needed": ["writing", "research"],
        "reward_usd": 0.0,
        "key": "auto-blog-task",
    },
    {
        "posted_by": "agent-analytics-v1",
        "title": "Analyze recent API usage patterns",
        "description": "Review the /stats endpoint data and identify which endpoints are most popular, any usage spikes, and opportunities to improve the service.",
        "skills_needed": ["analyze", "data"],
        "reward_usd": 0.0,
        "key": "auto-analytics-task",
    },
]

_economy_task_keys_posted: set = set()


def _run_agent_economy():
    """
    Autonomous agent economy loop — runs every 30 minutes.
    1. KnowledgeAgent seeds the knowledge base with API docs.
    2. Specialist agents auto-post tasks to the task board.
    3. Agents auto-claim and complete open tasks using Claude.
    """
    global _economy_stats
    now = datetime.utcnow().isoformat()
    _economy_stats["last_run"] = now

    # 1. Seed knowledge base (idempotent by entry_id)
    for seed in _KNOWLEDGE_SEEDS:
        try:
            add_knowledge(
                topic=seed["topic"],
                content=seed["content"],
                author_agent="agent-knowledge-v1",
                tags=seed["tags"],
                entry_id=seed["entry_id"],
            )
            _economy_stats["knowledge_seeded"] += 1
        except Exception:
            pass

    # 2. Auto-post tasks (once per key per process lifetime to avoid spam)
    for task_def in _AUTO_TASKS:
        key = task_def["key"]
        if key not in _economy_task_keys_posted:
            try:
                # Check if an open task with this title already exists
                existing = browse_tasks(status="open", limit=50)
                titles = [t["title"] for t in existing]
                if task_def["title"] not in titles:
                    submit_task(
                        posted_by=task_def["posted_by"],
                        title=task_def["title"],
                        description=task_def["description"],
                        skills_needed=task_def["skills_needed"],
                        reward_usd=task_def["reward_usd"],
                    )
                    _economy_stats["tasks_auto_posted"] += 1
                _economy_task_keys_posted.add(key)
            except Exception:
                pass

    # 3. Auto-claim and complete open tasks that match specialist capabilities
    _auto_complete_tasks()


def _auto_complete_tasks():
    """Scan open tasks and auto-complete those matching specialist agent skills."""
    open_tasks = browse_tasks(status="open", limit=20)
    for task in open_tasks:
        skills = task.get("skills_needed", [])
        title = task["title"]
        desc = task["description"]
        task_id = task["task_id"]

        # Match to a specialist agent
        agent_id = None
        if any(s in skills for s in ["writing", "content", "social-media"]):
            agent_id = "agent-content-v1"
        elif any(s in skills for s in ["research", "web-search"]):
            agent_id = "agent-search-v1"
        elif any(s in skills for s in ["analyze", "data", "compare"]):
            agent_id = "agent-analytics-v1"
        elif any(s in skills for s in ["rag", "knowledge-base", "fact-check"]):
            agent_id = "agent-knowledge-v1"
        elif any(s in skills for s in ["sentiment", "keywords", "classify"]):
            agent_id = "agent-nlp-v1"

        if not agent_id:
            continue

        # Claim it
        claimed = claim_task(task_id, agent_id)
        if not claimed:
            continue

        # Complete it with Claude
        try:
            msg = claude.messages.create(
                model=_get_model(),
                max_tokens=800,
                messages=[{
                    "role": "user",
                    "content": f"Complete this task as {agent_id}:\n\nTitle: {title}\n\nDescription: {desc}\n\nProvide a concise, useful result."
                }]
            )
            result_text = msg.content[0].text
            # Track cost
            track_cost(f"economy/{agent_id}", msg.model, msg.usage.input_tokens, msg.usage.output_tokens)
            complete_task(task_id, agent_id, result_text)
            _economy_stats["tasks_auto_completed"] += 1

            # If result is knowledge-worthy, add it to the KB
            if any(s in skills for s in ["research", "writing", "analyze"]):
                try:
                    add_knowledge(
                        topic=title[:80],
                        content=result_text[:1000],
                        author_agent=agent_id,
                        tags=skills,
                    )
                except Exception:
                    pass
        except Exception:
            pass


@admin_bp.route("/economy/status", methods=["GET"])
def economy_status():
    """Show autonomous agent economy stats."""
    open_tasks = browse_tasks(status="open", limit=50)
    completed_tasks = browse_tasks(status="completed", limit=50)
    return jsonify({
        "stats": _economy_stats,
        "task_board": {
            "open": len(open_tasks),
            "completed": len(completed_tasks),
        },
        "knowledge_base": {
            "trending": get_trending_topics(5),
        },
        "cost_today": get_daily_cost(),
        "throttled": is_cost_throttled(DAILY_COST_LIMIT_USD),
    })


# ── RSS Feed ──────────────────────────────────────────────────────────────────

@admin_bp.route("/feed.xml", methods=["GET"])
def rss_feed():
    """RSS 2.0 feed of blog posts — enables syndication to aggregators."""
    posts = list_blog_posts()
    items_xml = ""
    import re as _re2
    for p in posts[:20]:
        pub_date = p.get("generated_at", "")[:10]
        slug = p["slug"]
        link = f"https://api.aipaygen.com/blog/{slug}"
        full = get_blog_post(slug)
        raw = full.get("content", "") if full else ""
        raw = _re2.sub(r'^```html\s*', '', raw)
        desc = _re2.sub(r'<[^>]+>', '', raw)[:300].strip()
        if not desc:
            desc = p.get("title", "")
        items_xml += f"""
  <item>
    <title><![CDATA[{p['title']}]]></title>
    <link>{link}</link>
    <guid isPermaLink="true">{link}</guid>
    <description><![CDATA[{desc}]]></description>
    <pubDate>{pub_date}</pubDate>
    <category>{p.get('endpoint','api')}</category>
  </item>"""

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>AiPayGen Developer Blog</title>
    <link>https://api.aipaygen.com/blog</link>
    <description>Developer tutorials for building AI agents with AiPayGen — 155 tools and 140+ Claude-powered API endpoints. First 10 calls/day free.</description>
    <language>en-us</language>
    <atom:link href="https://api.aipaygen.com/feed.xml" rel="self" type="application/rss+xml"/>
    <image>
      <url>https://api.aipaygen.com/og-image.png</url>
      <title>AiPayGen</title>
      <link>https://api.aipaygen.com</link>
    </image>
    {items_xml}
  </channel>
</rss>"""
    return rss, 200, {"Content-Type": "application/rss+xml; charset=utf-8"}


# ── OG Image (SVG served as PNG fallback) ─────────────────────────────────────

@admin_bp.route("/og-image.png", methods=["GET"])
def og_image():
    """Social sharing card image — returned as inline SVG (browsers + crawlers accept it)."""
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0a0a0a"/>
      <stop offset="100%" stop-color="#1e1b4b"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="60" y="60" width="1080" height="510" rx="20" fill="#141414" opacity="0.8"/>
  <text x="600" y="220" font-family="system-ui,sans-serif" font-size="72" font-weight="800" fill="#ffffff" text-anchor="middle">AiPayGen</text>
  <text x="600" y="310" font-family="system-ui,sans-serif" font-size="32" fill="#a78bfa" text-anchor="middle">Pay-per-use Claude AI API</text>
  <text x="600" y="390" font-family="system-ui,sans-serif" font-size="26" fill="#888" text-anchor="middle">155 tools · 15 models · 4100+ APIs · No signup</text>
  <text x="600" y="460" font-family="system-ui,sans-serif" font-size="22" fill="#6366f1" text-anchor="middle">api.aipaygen.com</text>
  <rect x="440" y="490" width="320" height="48" rx="24" fill="#6366f1"/>
  <text x="600" y="521" font-family="system-ui,sans-serif" font-size="20" font-weight="600" fill="#fff" text-anchor="middle">Try free — no credit card</text>
</svg>"""
    return svg, 200, {"Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=86400"}


@admin_bp.route("/favicon.svg")
def favicon_svg():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#6366f1"/>
  <text x="32" y="46" font-family="system-ui,sans-serif" font-size="36" font-weight="800" fill="#fff" text-anchor="middle">Ai</text>
</svg>"""
    return svg, 200, {"Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=604800"}


@admin_bp.route("/favicon.ico")
def favicon_ico():
    return "", 204


# ── Changelog ─────────────────────────────────────────────────────────────────

@admin_bp.route("/changelog", methods=["GET"])
def changelog():
    """Auto-generated changelog showing recent blog posts, new endpoints, and stats."""
    posts = list_blog_posts()[:5]
    post_items = "".join(
        f'<li><a href="/blog/{p["slug"]}">{p["title"]}</a> <small style="color:#888">({p.get("generated_at","")[:10]})</small></li>'
        for p in posts
    )
    # Get payment stats
    total_calls = 0
    total_earned = 0.0
    try:
        if os.path.exists(PAYMENTS_LOG):
            with open(PAYMENTS_LOG) as f:
                entries = [json.loads(l) for l in f if l.strip()]
            total_calls = len(entries)
            total_earned = sum(e.get("amount_usd", 0) for e in entries)
    except Exception:
        pass

    cost = get_daily_cost()
    health = run_canary.__module__  # just to confirm import OK

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AiPayGen Changelog</title>
<meta name="description" content="What's new at AiPayGen — latest blog posts, API updates, and service stats.">
<link rel="canonical" href="https://api.aipaygen.com/changelog">
<meta property="og:title" content="AiPayGen Changelog">
<meta property="og:url" content="https://api.aipaygen.com/changelog">
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;line-height:1.7;color:#1a1a1a}}
a{{color:#6366f1}}h1,h2{{color:#1e1b4b}}.stat{{display:inline-block;background:#f8f7ff;border:1px solid #e0e0ff;border-radius:8px;padding:10px 20px;margin:6px;text-align:center}}
.stat .n{{font-size:1.8rem;font-weight:800;color:#6366f1}}.stat .l{{font-size:0.8rem;color:#888}}</style>
</head>
<body>
<p><a href="/">← Home</a></p>
<h1>Changelog</h1>
<p>Live service status and recent updates for <a href="https://api.aipaygen.com">api.aipaygen.com</a>.</p>

<h2>Service Stats</h2>
<div>
  <div class="stat"><div class="n">{total_calls:,}</div><div class="l">Total API calls</div></div>
  <div class="stat"><div class="n">${total_earned:.2f}</div><div class="l">Revenue logged</div></div>
  <div class="stat"><div class="n">161</div><div class="l">MCP Tools</div></div>
  <div class="stat"><div class="n">3</div><div class="l">Free calls/day</div></div>
  <div class="stat"><div class="n">${cost['total_cost_usd']:.4f}</div><div class="l">Claude cost today</div></div>
</div>

<h2>Recent Blog Posts</h2>
<ul>{post_items}</ul>
<p><a href="/blog">All posts →</a> · <a href="/feed.xml">RSS →</a></p>

<h2>Recent Updates</h2>
<ul>
  <li><strong>Mar 2026</strong> — Self-sufficiency: canary monitoring, trending blog auto-generation, agent economy, per-IP rate limiting, DB self-maintenance</li>
  <li><strong>Mar 2026</strong> — SocialBot cross-promotion: AiPayGen brand posting to Twitter + LinkedIn daily</li>
  <li><strong>Mar 2026</strong> — Referral system (10% commission), discovery engine (GitHub outreach, sitemap pings)</li>
  <li><strong>Mar 2026</strong> — Async jobs, file storage, webhook relay, free data tier (14+ endpoints)</li>
  <li><strong>Mar 2026</strong> — Prepaid API keys (Stripe), SSE streaming, MCP server (79 tools)</li>
  <li><strong>Mar 2026</strong> — 155 tools and 140+ endpoints: AI, scraping, code execution, agent messaging, task board, knowledge base</li>
</ul>

<p style="color:#888;font-size:0.85rem">Auto-updated · <a href="https://api.aipaygen.com/health">Health status</a> · <a href="https://api.aipaygen.com/self-test">Canary test</a></p>
</body>
</html>"""
    return Response(html, content_type="text/html")


# ── IndexNow — Instant Bing/Yandex Indexing for New Pages ────────────────────

@admin_bp.route(f"/{INDEXNOW_KEY}.txt", methods=["GET"])
def indexnow_verify():
    """IndexNow key verification file — required by Bing/Yandex."""
    return INDEXNOW_KEY, 200, {"Content-Type": "text/plain"}


def ping_indexnow(urls: list):
    """Ping IndexNow to get pages indexed on Bing/Yandex immediately."""
    try:
        payload = {
            "host": "api.aipaygen.com",
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://api.aipaygen.com/{INDEXNOW_KEY}.txt",
            "urlList": urls,
        }
        _requests.post(
            "https://api.indexnow.org/indexnow",
            json=payload,
            timeout=8,
        )
    except Exception:
        pass


# ── Dev.to Cross-Posting ──────────────────────────────────────────────────────

def crosspost_to_devto(title: str, content_html: str, slug: str, tags: list = None) -> dict:
    """
    Cross-post a blog post to dev.to via their API.
    Set DEVTO_API_KEY in .env to enable (get from dev.to/settings/extensions).
    """
    if not DEVTO_API_KEY:
        return {"skipped": "DEVTO_API_KEY not set"}
    try:
        import re as _re3
        # Convert HTML to markdown-ish for dev.to (it accepts both)
        markdown_body = _re3.sub(r'<[^>]+>', '', content_html)
        article = {
            "article": {
                "title": title,
                "published": True,
                "body_markdown": (
                    f"{markdown_body}\n\n"
                    f"---\n"
                    f"*Try it free at [api.aipaygen.com](https://api.aipaygen.com) — 10 calls/day, no credit card.*\n"
                    f"*Original post: [api.aipaygen.com/blog/{slug}](https://api.aipaygen.com/blog/{slug})*"
                ),
                "tags": (tags or ["ai", "api", "python"])[:4],
                "canonical_url": f"https://api.aipaygen.com/blog/{slug}",
                "series": "AiPayGen Developer Tutorials",
            }
        }
        resp = _requests.post(
            "https://dev.to/api/articles",
            json=article,
            headers={"api-key": DEVTO_API_KEY, "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {"posted": True, "url": data.get("url", ""), "id": data.get("id")}
        return {"posted": False, "status": resp.status_code, "detail": resp.text[:200]}
    except Exception as e:
        return {"posted": False, "error": str(e)}


# ── Reddit Post Generator ─────────────────────────────────────────────────────

@admin_bp.route("/reddit-posts", methods=["GET"])
def reddit_posts():
    """
    Returns ready-to-copy posts for key subreddits.
    Post these manually on launch day for max initial traffic.
    """
    posts = list_blog_posts()
    top_post = posts[0] if posts else {"title": "AiPayGen API", "slug": ""}
    subreddits = [
        {
            "subreddit": "r/MachineLearning",
            "title": "[P] AiPayGen — Pay-per-use Claude API with 155 tools and 140+ endpoints. Free tier (10/day), x402 crypto payments, MCP tools.",
            "body": f"""I built a pay-per-use AI API on top of Claude with 155 tools and 140+ endpoints — research, write, code, analyze, scrape, RAG, vision, diagrams, and more.

**Key features:**
- First 10 calls/day completely free (no signup, no key)
- Pay per call with Stripe ($5 for ~500 calls) or USDC on Base via x402
- 79 MCP tools for Claude Code/Desktop
- Agent infrastructure: messaging, task board, file storage, webhook relay, async jobs
- 14+ free real-time data endpoints (weather, crypto, news, Wikipedia, arXiv)

```bash
curl https://api.aipaygen.com/research \\
  -H "Content-Type: application/json" \\
  -d '{{"topic": "transformer attention mechanisms"}}'
```

API: https://api.aipaygen.com
OpenAPI: https://api.aipaygen.com/openapi.json
Blog: https://api.aipaygen.com/blog""",
        },
        {
            "subreddit": "r/LocalLLaMA",
            "title": "AiPayGen — Claude API with x402 micropayments. Agents can pay per call with USDC, 10 free calls/day",
            "body": f"""Built a micro-payment AI API for agent-to-agent use. Your AI agent can call it autonomously using x402 (HTTP 402 payment protocol) with USDC on Base, or just use the free tier.

**Why this is interesting for agents:**
- True pay-per-call (not subscription) — agents pay exactly what they use
- No API key management — pay with USDC or use free daily quota
- 79 MCP tools for integration with Claude Code/Desktop
- Agent task board, messaging, memory, webhook relay built in

Try it: https://api.aipaygen.com/preview (no auth needed)""",
        },
        {
            "subreddit": "r/selfhosted",
            "title": "I built a pay-per-use AI API (Claude-powered) that runs on a Raspberry Pi — x402 payments, 155 tools",
            "body": f"""Running on a Raspberry Pi 5 at home behind Cloudflare tunnel.

Stack: Flask + Gunicorn + SQLite + APScheduler + Cloudflare tunnel + systemd

It handles x402 payment verification, API key management, referral tracking, scheduled blog generation, and 155 tools and 140+ Claude-powered endpoints — all on a Pi.

What surprised me: SQLite handles this fine for the traffic volume a self-hosted project gets.

Live at: https://api.aipaygen.com
Source architecture explained: https://api.aipaygen.com/blog""",
        },
        {
            "subreddit": "r/Python",
            "title": "I built a pay-per-use REST API with Flask that accepts crypto micropayments (x402) — here's how",
            "body": f"""Tutorial post: {top_post['title']}
https://api.aipaygen.com/blog/{top_post.get('slug', '')}

The core pattern: wrap Flask routes with x402 payment middleware. When an agent calls the endpoint without payment, it gets HTTP 402 with payment instructions. Client attaches a signed USDC transaction header, retries, and gets the result.

Full Python client example in the blog post above.""",
        },
    ]
    return jsonify({"subreddits": subreddits, "note": "Copy-paste these for launch day. Post during peak hours 9am-12pm EST."})


@admin_bp.route("/admin/crypto/deposits", methods=["GET"])
@require_admin
def admin_crypto_deposits():
    from crypto_deposits import get_all_deposits
    limit = int(request.args.get("limit", 100))
    deposits = get_all_deposits(limit=limit)
    return jsonify({"deposits": deposits, "count": len(deposits)})
