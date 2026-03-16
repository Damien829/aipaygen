"""
Admin, discovery management, referral, blog, economy, self-test, health history,
costs, and miscellaneous admin endpoints — extracted from app.py as a Blueprint.
"""

import hmac
import os
import re as _re
import json
import base64
import hmac
import requests as _requests
from datetime import datetime
import logging

from flask import Blueprint, request, jsonify, render_template, Response

logger = logging.getLogger(__name__)

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
from funnel_tracker import get_funnel_stats, get_analytics as _get_analytics, is_bot
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
        if admin_secret and hmac.compare_digest(key, admin_secret):
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
    elif not admin_secret:
        return redirect("/admin/login")
    # Check query param or header
    elif hmac.compare_digest(request.form.get("key", ""), admin_secret):
        session["admin"] = True  # set cookie for future visits
    elif hmac.compare_digest(request.headers.get("X-Admin-Key", ""), admin_secret):
        pass
    elif hmac.compare_digest(request.headers.get("Authorization", "").replace("Bearer ", ""), admin_secret):
        pass
    else:
        return redirect("/admin/login")
    try:
        days = max(1, min(365, int(request.args.get("days", 7))))
    except (ValueError, TypeError):
        days = 7
    stats = get_funnel_stats(days)
    by_type = stats.get("by_type", {})

    # Key attribution stats
    import sqlite3 as _sqlite3
    import api_keys as _ak
    key_stats_html = ""
    median_label = "N/A"
    try:
        with _sqlite3.connect(_ak.DB_PATH) as kc:
            kc.row_factory = _sqlite3.Row
            rows = kc.execute("""
                SELECT COALESCE(source, 'unknown') as source,
                       COUNT(*) as total,
                       SUM(CASE WHEN call_count = 0 THEN 1 ELSE 0 END) as zero_calls,
                       SUM(CASE WHEN call_count > 0 THEN 1 ELSE 0 END) as active
                FROM api_keys WHERE is_active = 1
                GROUP BY source ORDER BY total DESC
            """).fetchall()
            for r in rows:
                pct = round(100 * r["active"] / r["total"], 1) if r["total"] else 0
                key_stats_html += (
                    f'<tr><td>{r["source"]}</td><td>{r["total"]}</td>'
                    f'<td style="color:#f87171">{r["zero_calls"]}</td><td style="color:#34d399">{r["active"]}</td><td>{pct}%</td></tr>'
                )
            median_row = kc.execute("""
                SELECT first_used_at, created_at FROM api_keys
                WHERE first_used_at IS NOT NULL ORDER BY
                (julianday(first_used_at) - julianday(created_at))
                LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM api_keys WHERE first_used_at IS NOT NULL)
            """).fetchone()
            if median_row:
                from datetime import datetime as _dt
                created = _dt.fromisoformat(median_row["created_at"])
                first = _dt.fromisoformat(median_row["first_used_at"])
                median_mins = round((first - created).total_seconds() / 60, 1)
                median_label = f"{median_mins} min" if median_mins < 60 else f"{round(median_mins/60, 1)} hr"
    except Exception:
        key_stats_html = '<tr><td colspan="5" style="color:#555">Error loading key stats</td></tr>'

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

  <div class="card" style="margin-top:24px">
    <h2 style="margin-top:0;margin-bottom:8px">Key Attribution</h2>
    <p style="color:#888;margin-bottom:12px">Median time to first call: <b style="color:#6366f1">{median_label}</b></p>
    <table style="width:100%;border-collapse:collapse">
      <tr style="color:#888;text-align:left;border-bottom:1px solid #2a2a2a"><th style="padding:8px">Source</th><th style="padding:8px">Keys</th><th style="padding:8px">0 Calls</th><th style="padding:8px">Active</th><th style="padding:8px">Activation %</th></tr>
      {key_stats_html}
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
    # Static (hand-written) posts — shown first
    static_posts = [
        {"slug": "launch", "title": "Why I Built AiPayGen: 250 AI Tools for the Price of One API Call", "generated_at": "2026-03-15"},
        {"slug": "5-things-you-can-build", "title": "5 Things You Can Build with 250 AI Tools", "generated_at": "2026-03-15"},
        {"slug": "x402-explained", "title": "How x402 Makes AI APIs Pay-Per-Use", "generated_at": "2026-03-15"},
    ]
    db_posts = list_blog_posts()
    # Merge: static first, then DB posts (skip duplicates by slug)
    static_slugs = {p["slug"] for p in static_posts}
    posts = static_posts + [p for p in db_posts if p["slug"] not in static_slugs]
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
<meta name="description" content="Developer tutorials for building with AiPayGen — 250 tools and 140+ Claude-powered AI API endpoints. Covers AI agents, scraping, x402 payments, real-time data, and more. First 3 calls/day free.">
<link rel="canonical" href="https://api.aipaygen.com/blog">
<link rel="alternate" type="application/rss+xml" title="AiPayGen Blog RSS" href="/feed.xml">
<meta property="og:type" content="website">
<meta property="og:title" content="AiPayGen Developer Blog">
<meta property="og:description" content="Tutorials for building AI agents and automations with AiPayGen's 250 tools and 140+ Claude-powered endpoints.">
<meta property="og:url" content="https://aipaygen.com/blog">
<meta property="og:image" content="https://aipaygen.com/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps({"@context":"https://schema.org","@type":"Blog","name":"AiPayGen Developer Blog","url":"https://aipaygen.com/blog","description":"Developer tutorials for AI agent APIs","publisher":{"@type":"Organization","name":"AiPayGen","url":"https://aipaygen.com"}})}</script>
<style>body{{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6;color:#1a1a1a}}a{{color:#6366f1}}h1{{color:#1e1b4b}}.rss{{float:right;font-size:0.85rem;background:#f4f4f4;padding:4px 10px;border-radius:20px;text-decoration:none;color:#555}}</style>
</head>
<body>
<nav style="background:#f8f7ff;padding:10px 20px;border-radius:8px;margin-bottom:24px;font-size:0.9rem">
<a href="/try" style="margin-right:12px">Try Free</a>
<a href="/docs" style="margin-right:12px">Docs</a>
<a href="/pricing" style="margin-right:12px">Pricing</a>
<a href="/playground" style="margin-right:12px">Playground</a>
<a href="/examples" style="margin-right:12px">Examples</a>
<a href="/status" style="margin-right:12px">Status</a>
<a href="/buy-credits" style="font-weight:600">Get API Key</a>
</nav>
<a class="rss" href="/feed.xml">RSS feed</a>
<h1>AiPayGen Developer Blog</h1>
<p>Tutorials for building AI agents with AiPayGen — 250 tools and 140+ Claude-powered endpoints. <strong>First 3 calls/day free.</strong></p>
<ul style="padding-left:1.2rem">{items}</ul>
<p><a href="https://api.aipaygen.com/discover">Browse all 250 tools and 140+ endpoints →</a> · <a href="https://api.aipaygen.com/buy-credits">Buy credits ($5+) →</a></p>
</body>
</html>"""
    resp = Response(html, content_type="text/html")
    resp.headers["Link"] = '</feed.xml>; rel="alternate"; type="application/rss+xml"'
    return resp


@admin_bp.route("/blog/launch", methods=["GET"])
def blog_launch():
    """Static launch blog post — served from Jinja template."""
    return render_template("blog_launch.html")


@admin_bp.route("/blog/5-things-you-can-build", methods=["GET"])
def blog_5_things():
    """Static blog post — 5 things you can build with 250 AI tools."""
    return render_template("blog_5_things.html")


@admin_bp.route("/blog/x402-explained", methods=["GET"])
def blog_x402():
    """Static blog post — how x402 makes AI APIs pay-per-use."""
    return render_template("blog_x402.html")


@admin_bp.route("/blog/<slug>", methods=["GET"])
def blog_post(slug):
    from security import sanitize_html
    post = get_blog_post(slug)
    if not post:
        return jsonify({"error": "post not found"}), 404
    # Sanitize title for use in HTML attributes and text (content is trusted AI-generated HTML)
    safe_title = sanitize_html(post['title'])
    canonical = f"https://api.aipaygen.com/blog/{sanitize_html(slug)}"
    desc = f"{safe_title} — Developer tutorial for AiPayGen, the pay-per-use Claude AI API with 250 tools and 140+ endpoints."
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
<meta property="og:image" content="https://aipaygen.com/og-image.png">
<meta property="og:site_name" content="AiPayGen">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{safe_title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="https://aipaygen.com/og-image.png">
<script type="application/ld+json">{jsonld}</script>
<style>
body{{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.7;color:#1a1a1a}}
code,pre{{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:0.9em;font-family:monospace}}
pre{{padding:16px;overflow-x:auto;display:block}}a{{color:#6366f1}}h1{{color:#1e1b4b;font-size:1.9rem}}
.nav{{color:#888;margin-bottom:2rem;font-size:0.9rem}}.cta{{background:#f8f7ff;border:1px solid #e0e0ff;border-radius:8px;padding:16px;margin:2rem 0}}
</style>
</head>
<body>
<nav style="background:#f8f7ff;padding:10px 20px;border-radius:8px;margin-bottom:16px;font-size:0.9rem">
<a href="/try" style="margin-right:12px">Try Free</a>
<a href="/docs" style="margin-right:12px">Docs</a>
<a href="/pricing" style="margin-right:12px">Pricing</a>
<a href="/playground" style="margin-right:12px">Playground</a>
<a href="/examples" style="margin-right:12px">Examples</a>
<a href="/status" style="margin-right:12px">Status</a>
<a href="/buy-credits" style="font-weight:600">Get API Key</a>
</nav>
<div class="nav"><a href="/blog">← All posts</a> · <a href="https://aipaygen.com">AiPayGen API</a> · <a href="/discover">250 tools</a></div>
<h1>{safe_title}</h1>
{post['content']}
<div class="cta">
  <strong>Try it free →</strong> First 3 calls/day free, no credit card. <a href="https://api.aipaygen.com/discover">Browse all 250 tools and 140+ endpoints</a> or <a href="https://api.aipaygen.com/buy-credits">buy credits ($5+)</a>.
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
        logger.error("x402 spend stats failed: %s", e)
        return jsonify({"error": "Failed to retrieve spend stats"})


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
        logger.error("File upload validation error: %s", e)
        return jsonify({"error": "File upload failed: size or format limit exceeded"}), 413


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

@admin_bp.route("/admin/funnel-data")
@require_admin
def admin_funnel_data():
    """Conversion funnel stats. ?days=7 (default). Protected by ADMIN_SECRET."""
    days = request.args.get("days", 7, type=int)
    days = min(max(days, 1), 365)
    stats = get_funnel_stats(days=days)
    return jsonify(stats)


@admin_bp.route("/admin/ab-results")
@require_admin
def admin_ab_results():
    """A/B test results dashboard. ?test=landing_hero_v1&days=30"""
    try:
        from ab_testing import get_test_results, list_tests
    except ImportError:
        return jsonify({"error": "A/B testing module not available"}), 500
    test_name = request.args.get("test", "")
    days = min(max(request.args.get("days", 30, type=int), 1), 365)
    if test_name:
        return jsonify(get_test_results(test_name, days=days))
    return jsonify({"tests": list_tests(days=days)})


@admin_bp.route("/admin/funnel-enhanced")
@require_admin
def admin_funnel_enhanced():
    """Enhanced conversion funnel with drop-off analysis and cohort comparison."""
    from datetime import timedelta
    import sqlite3 as _sq

    days = min(max(request.args.get("days", 30, type=int), 1), 365)
    base_dir = os.path.dirname(os.path.dirname(__file__))
    funnel_db = os.path.join(base_dir, "funnel.db")
    keys_db = os.path.join(base_dir, "api_keys.db")

    now = datetime.utcnow()
    cutoff = (now - timedelta(days=days)).isoformat()

    # ── Full funnel with percentages ──
    stages = [
        ("Visit", "discover_hit"),
        ("Try Demo", "demo_used"),
        ("Generate Key", "key_generated"),
        ("Add Credits", "credits_bought"),
        ("Make Paid Call", "paid_call"),
    ]

    funnel = []
    first_count = None
    prev_count = None

    try:
        with _sq.connect(funnel_db) as c:
            c.row_factory = _sq.Row
            for label, event_type in stages:
                row = c.execute(
                    "SELECT COUNT(*) as cnt FROM funnel_events WHERE event_type = ? AND (is_bot IS NULL OR is_bot = 0) AND created_at >= ?",
                    (event_type, cutoff),
                ).fetchone()
                count = row["cnt"] if row else 0
                if first_count is None and count > 0:
                    first_count = count
                step_pct = round(100 * count / prev_count, 1) if prev_count and prev_count > 0 else None
                overall_pct = round(100 * count / first_count, 1) if first_count and first_count > 0 and count != first_count else None
                drop_off = prev_count - count if prev_count is not None and prev_count > count else 0
                funnel.append({
                    "stage": label,
                    "event": event_type,
                    "count": count,
                    "step_conversion_pct": step_pct,
                    "overall_conversion_pct": overall_pct,
                    "drop_off": drop_off,
                })
                prev_count = count if count > 0 else prev_count

            # ── Drop-off by last page ──
            drop_off_pages = []
            for i in range(len(stages) - 1):
                current_event = stages[i][1]
                next_event = stages[i + 1][1]
                # IPs that did current but not next
                dropped = c.execute(
                    "SELECT COUNT(DISTINCT ip) as cnt FROM funnel_events "
                    "WHERE event_type = ? AND (is_bot IS NULL OR is_bot = 0) AND created_at >= ? "
                    "AND ip NOT IN (SELECT DISTINCT ip FROM funnel_events WHERE event_type = ? AND created_at >= ?)",
                    (current_event, cutoff, next_event, cutoff),
                ).fetchone()["cnt"]
                drop_off_pages.append({
                    "from_stage": stages[i][0],
                    "to_stage": stages[i + 1][0],
                    "dropped_visitors": dropped,
                })

            # ── Cohort analysis: this week vs last week ──
            this_week_start = (now - timedelta(days=7)).isoformat()
            last_week_start = (now - timedelta(days=14)).isoformat()
            last_week_end = this_week_start

            cohorts = {}
            for cohort_label, c_start, c_end in [("this_week", this_week_start, now.isoformat()), ("last_week", last_week_start, last_week_end)]:
                cohort_data = {}
                for label, event_type in stages:
                    row = c.execute(
                        "SELECT COUNT(*) as cnt FROM funnel_events WHERE event_type = ? AND (is_bot IS NULL OR is_bot = 0) AND created_at >= ? AND created_at < ?",
                        (event_type, c_start, c_end),
                    ).fetchone()
                    cohort_data[label] = row["cnt"] if row else 0
                cohorts[cohort_label] = cohort_data

    except Exception as e:
        logger.exception("Enhanced funnel query failed")
        return jsonify({"error": "Query failed"}), 500

    # ── A/B test results ──
    ab_results = {}
    try:
        from ab_testing import get_test_results, list_tests
        tests = list_tests(days=days)
        for t in tests:
            ab_results[t["test_name"]] = get_test_results(t["test_name"], days=days)
    except Exception:
        pass

    result = {
        "period_days": days,
        "funnel": funnel,
        "drop_off_analysis": drop_off_pages,
        "cohorts": cohorts,
        "ab_tests": ab_results,
    }

    # HTML or JSON
    if request.args.get("format") == "json":
        return jsonify(result)

    # Build HTML dashboard
    def _n(v):
        return f"{v:,}" if v else "0"

    funnel_rows = ""
    for f in funnel:
        bar_w = round(100 * f["count"] / (first_count or 1)) if first_count else 0
        step_str = f'{f["step_conversion_pct"]}%' if f["step_conversion_pct"] is not None else "-"
        overall_str = f'{f["overall_conversion_pct"]}%' if f["overall_conversion_pct"] is not None else "100%"
        funnel_rows += (
            f'<tr><td>{f["stage"]}</td><td>{_n(f["count"])}</td>'
            f'<td><div style="background:#1e1e1e;border-radius:4px;height:20px;overflow:hidden">'
            f'<div style="background:#6366f1;height:100%;width:{bar_w}%;border-radius:4px"></div></div></td>'
            f'<td>{step_str}</td><td>{overall_str}</td><td style="color:#f87171">{_n(f["drop_off"])}</td></tr>'
        )

    dropoff_rows = ""
    for d in drop_off_pages:
        dropoff_rows += f'<tr><td>{d["from_stage"]} &rarr; {d["to_stage"]}</td><td style="color:#f87171">{_n(d["dropped_visitors"])}</td></tr>'

    cohort_rows = ""
    for label, event_type in stages:
        tw = cohorts.get("this_week", {}).get(label, 0)
        lw = cohorts.get("last_week", {}).get(label, 0)
        change = tw - lw
        change_str = f'<span style="color:{"#34d399" if change >= 0 else "#f87171"}">{("+" if change > 0 else "")}{change}</span>'
        cohort_rows += f'<tr><td>{label}</td><td>{_n(lw)}</td><td>{_n(tw)}</td><td>{change_str}</td></tr>'

    ab_html = ""
    for test_name, tr in ab_results.items():
        winner = tr.get("winner", "?")
        lift = tr.get("lift", 0)
        a = tr.get("variants", {}).get("A", {})
        b = tr.get("variants", {}).get("B", {})
        ab_html += (
            f'<div class="card" style="margin-bottom:16px">'
            f'<h3 style="margin:0 0 12px;color:#a5b4fc">{test_name}</h3>'
            f'<table><tr><th>Variant</th><th>Visitors</th><th>Conversions</th><th>Rate</th></tr>'
            f'<tr><td>A (control)</td><td>{_n(a.get("visitors", 0))}</td><td>{_n(a.get("conversions", 0))}</td><td>{a.get("conversion_rate", 0)}%</td></tr>'
            f'<tr><td>B (test)</td><td>{_n(b.get("visitors", 0))}</td><td>{_n(b.get("conversions", 0))}</td><td>{b.get("conversion_rate", 0)}%</td></tr>'
            f'</table>'
            f'<div style="margin-top:10px;font-size:0.85rem">'
            f'Winner: <span style="color:#34d399;font-weight:700">{winner}</span>'
            f'{f" (+{lift}% lift)" if lift else ""}'
            f' &middot; Confidence: {tr.get("confidence", "normal")}'
            f'</div></div>'
        )
    if not ab_html:
        ab_html = '<p style="color:#555">No A/B tests running yet</p>'

    html = (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Enhanced Funnel - AiPayGen Admin</title>'
        '<style>'
        '*{box-sizing:border-box;margin:0;padding:0}'
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0a0a0a;color:#e8e8e8;padding:24px 16px}'
        '.wrap{max-width:1000px;margin:0 auto}'
        'h1{font-size:1.5rem;margin-bottom:4px;color:#fff}'
        'h2{font-size:1.1rem;margin:28px 0 12px;color:#a5b4fc}'
        'h3{font-size:1rem}'
        '.sub{color:#888;font-size:0.82rem;margin-bottom:20px}'
        '.card{background:#141414;border:1px solid #2a2a2a;border-radius:14px;padding:20px;margin-bottom:16px}'
        'table{width:100%;border-collapse:collapse;font-size:0.82rem}'
        'th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #1e1e1e}'
        'th{color:#666;font-weight:600;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.5px}'
        'a{color:#6366f1;text-decoration:none}'
        '.nav{display:flex;gap:12px;margin-bottom:20px}'
        '.nav a{padding:6px 14px;border-radius:6px;background:#1e1e1e;color:#888;font-size:0.82rem;border:1px solid #2a2a2a}'
        '.nav a.active{background:#6366f1;color:#fff;border-color:#6366f1}'
        '</style></head><body>'
        '<div class="wrap">'
        '<h1>Enhanced Conversion Funnel</h1>'
        f'<p class="sub">Last {days} days</p>'
        '<div class="nav">'
        '<a href="/admin/funnel">Basic Funnel</a>'
        '<a href="/admin/funnel-enhanced" class="active">Enhanced Funnel</a>'
        '<a href="/admin/analytics">Analytics</a>'
        '</div>'
        '<div class="card"><h2>Conversion Funnel</h2>'
        '<table><tr><th>Stage</th><th>Count</th><th>Bar</th><th>Step %</th><th>Overall %</th><th>Drop-off</th></tr>'
        f'{funnel_rows}</table></div>'
        '<div class="card"><h2>Drop-off Analysis</h2>'
        '<table><tr><th>Transition</th><th>Dropped Visitors</th></tr>'
        f'{dropoff_rows}</table></div>'
        '<div class="card"><h2>Cohort Comparison (This Week vs Last Week)</h2>'
        '<table><tr><th>Stage</th><th>Last Week</th><th>This Week</th><th>Change</th></tr>'
        f'{cohort_rows}</table></div>'
        f'<h2>A/B Test Results</h2>{ab_html}'
        '</div></body></html>'
    )
    return html, 200, {"Content-Type": "text/html"}


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
    try:
        limit = max(1, min(1000, int(request.args.get("limit", 100))))
    except (ValueError, TypeError):
        limit = 100
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
            "AiPayGen API (https://api.aipaygen.com) has 250 tools and 140+ endpoints. "
            "Key endpoints: /research ($0.01), /write ($0.05), /analyze ($0.02), /code ($0.05), "
            "/scrape/google-maps ($0.10), /chain ($0.25 for 5-step pipelines), /rag ($0.05). "
            "Free tier: 3 calls/day per IP. Prepaid keys: /buy-credits. "
            "OpenAPI spec: /openapi.json. MCP tools: /sdk."
        ),
        "tags": ["api", "aipaygen", "reference"],
        "entry_id": "kb-aipaygen-api-ref-v1",
    },
    {
        "topic": "x402-payment-protocol",
        "content": (
            "x402 V2 is the open payment protocol for AI agents. HTTP 402 response includes PAYMENT-REQUIRED header with payment details. "
            "Agents pay USDC on Base, Solana, or Stellar. AiPayGen wallet: 0x366D488a48de1B2773F3a21F1A6972715056Cb30. "
            "Facilitator: https://api.cdp.coinbase.com/platform/v2/x402. Use x402 SDK (pip install x402). "
            "x402 Foundation: Coinbase, Cloudflare, Google, Visa. Google AP2 compatible."
        ),
        "tags": ["x402", "payment", "usdc", "base", "solana", "stellar", "v2"],
        "entry_id": "kb-x402-protocol-v2",
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
    <description>Developer tutorials for building AI agents with AiPayGen — 250 tools and 140+ Claude-powered API endpoints. First 3 calls/day free.</description>
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


# ── OG Image (PNG for social platforms) ───────────────────────────────────────

_og_png_cache = None  # module-level cache for generated PNG bytes

_OG_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
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
  <text x="600" y="390" font-family="system-ui,sans-serif" font-size="26" fill="#888" text-anchor="middle">250 tools · 15 models · 4100+ APIs · No signup</text>
  <text x="600" y="460" font-family="system-ui,sans-serif" font-size="22" fill="#6366f1" text-anchor="middle">api.aipaygen.com</text>
  <rect x="440" y="490" width="320" height="48" rx="24" fill="#6366f1"/>
  <text x="600" y="521" font-family="system-ui,sans-serif" font-size="20" font-weight="600" fill="#fff" text-anchor="middle">Try free — no credit card</text>
</svg>"""


def _generate_og_png():
    """Generate OG image as PNG bytes. Tries cairosvg, then Pillow, then returns None."""
    # Strategy 1: cairosvg (best quality — renders SVG faithfully)
    try:
        import cairosvg
        import io
        buf = io.BytesIO()
        cairosvg.svg2png(bytestring=_OG_SVG.encode("utf-8"), write_to=buf,
                         output_width=1200, output_height=630)
        return buf.getvalue()
    except Exception:
        pass

    # Strategy 2: Pillow — draw a simple card programmatically
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (1200, 630))
        draw = ImageDraw.Draw(img)
        # Gradient-ish background: dark with slight purple tint at bottom-right
        for y in range(630):
            r = int(10 + (30 - 10) * y / 630)
            g = int(10 + (27 - 10) * y / 630)
            b = int(10 + (75 - 10) * y / 630)
            draw.line([(0, y), (1199, y)], fill=(r, g, b))
        # Inner card
        draw.rounded_rectangle([60, 60, 1140, 570], radius=20, fill=(20, 20, 20, 204))
        # Text — use default font (always available), scale up with truetype if possible
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
            sub_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
            detail_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
            btn_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 19)
        except Exception:
            title_font = ImageFont.load_default()
            sub_font = title_font
            detail_font = title_font
            small_font = title_font
            btn_font = title_font
        # Title
        draw.text((600, 190), "AiPayGen", fill=(255, 255, 255), font=title_font, anchor="mm")
        # Subtitle
        draw.text((600, 280), "Pay-per-use Claude AI API", fill=(167, 139, 250), font=sub_font, anchor="mm")
        # Details
        draw.text((600, 360), "250 tools \u00b7 15 models \u00b7 4100+ APIs \u00b7 No signup",
                  fill=(136, 136, 136), font=detail_font, anchor="mm")
        # URL
        draw.text((600, 430), "api.aipaygen.com", fill=(99, 102, 241), font=small_font, anchor="mm")
        # Button
        draw.rounded_rectangle([440, 470, 760, 518], radius=24, fill=(99, 102, 241))
        draw.text((600, 494), "Try free \u2014 no credit card", fill=(255, 255, 255), font=btn_font, anchor="mm")

        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        pass

    return None


@admin_bp.route("/og-image.png", methods=["GET"])
def og_image():
    """Social sharing card image — served as PNG for Twitter/LinkedIn/Facebook/Slack compatibility."""
    global _og_png_cache
    if _og_png_cache is None:
        _og_png_cache = _generate_og_png()
    if _og_png_cache:
        return _og_png_cache, 200, {"Content-Type": "image/png", "Cache-Control": "public, max-age=86400"}
    # Fallback: serve SVG (better than nothing)
    return _OG_SVG, 200, {"Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=86400"}


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

@admin_bp.route("/admin/changelog", methods=["GET"])
def admin_changelog():
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
<meta property="og:url" content="https://aipaygen.com/changelog">
<meta property="og:description" content="Latest updates, blog posts, and service stats for AiPayGen API.">
<meta property="og:image" content="https://aipaygen.com/og-image.png">
<meta name="twitter:card" content="summary_large_image">
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
  <div class="stat"><div class="n">169</div><div class="l">MCP Tools</div></div>
  <div class="stat"><div class="n">10</div><div class="l">Free calls/day</div></div>
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
  <li><strong>Mar 2026</strong> — 250 tools and 140+ endpoints: AI, scraping, code execution, agent messaging, task board, knowledge base</li>
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
                    f"*Try it free at [api.aipaygen.com](https://api.aipaygen.com) — 3 calls/day, no credit card.*\n"
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
        logger.error("Reddit post failed: %s", e)
        return {"posted": False, "error": "Post submission failed"}


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
            "title": "[P] AiPayGen — Pay-per-use Claude API with 250 tools and 140+ endpoints. Free tier (10/day), x402 crypto payments, MCP tools.",
            "body": f"""I built a pay-per-use AI API on top of Claude with 250 tools and 140+ endpoints — research, write, code, analyze, scrape, RAG, vision, diagrams, and more.

**Key features:**
- First 3 calls/day completely free (no signup, no key)
- Pay per call with Stripe ($5 for ~500 calls) or USDC via x402 V2 (Base, Solana, Stellar)
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
            "title": "AiPayGen — Claude API with x402 V2 micropayments. Agents pay per call with USDC on Base/Solana/Stellar, 3 free calls/day",
            "body": f"""Built a micro-payment AI API for agent-to-agent use. Your AI agent can call it autonomously using x402 V2 (HTTP 402 payment protocol) with USDC on Base, Solana, or Stellar — or just use the free tier.

**Why this is interesting for agents:**
- True pay-per-call (not subscription) — agents pay exactly what they use
- No API key management — pay with USDC or use free daily quota
- 79 MCP tools for integration with Claude Code/Desktop
- Agent task board, messaging, memory, webhook relay built in

Try it: https://api.aipaygen.com/preview (no auth needed)""",
        },
        {
            "subreddit": "r/selfhosted",
            "title": "I built a pay-per-use AI API (Claude-powered) that runs on a Raspberry Pi — x402 payments, 250 tools",
            "body": f"""Running on a Raspberry Pi 5 at home behind Cloudflare tunnel.

Stack: Flask + Gunicorn + SQLite + APScheduler + Cloudflare tunnel + systemd

It handles x402 payment verification, API key management, referral tracking, scheduled blog generation, and 250 tools and 140+ Claude-powered endpoints — all on a Pi.

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
    try:
        limit = max(1, min(1000, int(request.args.get("limit", 100))))
    except (ValueError, TypeError):
        limit = 100
    deposits = get_all_deposits(limit=limit)
    return jsonify({"deposits": deposits, "count": len(deposits)})


@admin_bp.route("/admin/clear-cache", methods=["POST"])
@require_admin
def admin_clear_cache():
    from model_router import clear_cache as _clear_model_cache
    from helpers import _ttl_cache, _ip_rate, _identity_rate
    _clear_model_cache()
    _ttl_cache.clear()
    _ip_rate.clear()
    _identity_rate.clear()
    return jsonify({"status": "ok", "message": "All caches cleared (model, TTL, rate limiters)"})


@admin_bp.route("/admin/restart", methods=["POST"])
@require_admin
def admin_restart_workers():
    """Gracefully restart gunicorn workers by sending HUP to the master process."""
    import signal
    try:
        master_pid = os.getppid()
        os.kill(master_pid, signal.SIGHUP)
        return jsonify({"status": "ok", "message": f"HUP sent to gunicorn master (pid {master_pid})"})
    except Exception:
        logger.exception("Failed to restart workers")
        return jsonify({"status": "error", "message": "Failed to restart workers"}), 500


@admin_bp.route("/admin/export")
@require_admin
def admin_export_data():
    """Export CSV of api_keys, funnel events, and tool usage."""
    import sqlite3 as _sq
    import csv
    import io

    export_type = request.args.get("type", "all")
    base_dir = os.path.dirname(os.path.dirname(__file__))
    output = io.StringIO()

    if export_type in ("keys", "all"):
        output.write("=== API KEYS ===\n")
        try:
            with _sq.connect(os.path.join(base_dir, "api_keys.db")) as conn:
                conn.row_factory = _sq.Row
                rows = conn.execute("SELECT id, key, label, balance_usd, total_spent, call_count, is_active, created_at, last_used_at, source FROM api_keys ORDER BY id").fetchall()
                writer = csv.writer(output)
                writer.writerow(["id", "key_prefix", "label", "balance_usd", "total_spent", "call_count", "is_active", "created_at", "last_used_at", "source"])
                for r in rows:
                    writer.writerow([r["id"], r["key"][:12] + "...", r["label"], r["balance_usd"], r["total_spent"], r["call_count"], r["is_active"], r["created_at"], r["last_used_at"], r["source"]])
        except Exception:
            output.write("(no api_keys data)\n")
        output.write("\n")

    if export_type in ("funnel", "all"):
        output.write("=== FUNNEL EVENTS ===\n")
        try:
            with _sq.connect(os.path.join(base_dir, "funnel.db")) as conn:
                conn.row_factory = _sq.Row
                rows = conn.execute("SELECT id, event_type, endpoint, ip, is_bot, created_at FROM funnel_events ORDER BY id DESC LIMIT 5000").fetchall()
                writer = csv.writer(output)
                writer.writerow(["id", "event_type", "endpoint", "ip", "is_bot", "created_at"])
                for r in rows:
                    writer.writerow([r["id"], r["event_type"], r["endpoint"], r["ip"], r["is_bot"], r["created_at"]])
        except Exception:
            output.write("(no funnel data)\n")
        output.write("\n")

    if export_type in ("tools", "all"):
        output.write("=== TOOL USAGE ===\n")
        try:
            with _sq.connect(os.path.join(base_dir, "tool_usage.db")) as conn:
                conn.row_factory = _sq.Row
                rows = conn.execute("SELECT tool_name, api_key, count, last_used FROM tool_usage ORDER BY count DESC LIMIT 5000").fetchall()
                writer = csv.writer(output)
                writer.writerow(["tool_name", "api_key_prefix", "count", "last_used"])
                for r in rows:
                    writer.writerow([r["tool_name"], (r["api_key"] or "")[:12] + "...", r["count"], r["last_used"]])
        except Exception:
            output.write("(no tool_usage data)\n")

    now_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=aipaygen_export_{now_str}.csv"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS — Comprehensive admin dashboard
# ══════════════════════════════════════════════════════════════════════════════

def _query_db(db_path, query, params=()):
    """Helper: run a query on a SQLite DB, return list of dicts."""
    import sqlite3 as _sq
    try:
        with _sq.connect(db_path) as conn:
            conn.row_factory = _sq.Row
            return [dict(r) for r in conn.execute(query, params).fetchall()]
    except Exception:
        return []


def _query_one(db_path, query, params=()):
    """Helper: run a query returning a single row dict."""
    import sqlite3 as _sq
    try:
        with _sq.connect(db_path) as conn:
            conn.row_factory = _sq.Row
            row = conn.execute(query, params).fetchone()
            return dict(row) if row else {}
    except Exception:
        return {}


@admin_bp.route("/admin/analytics")
@require_admin
def admin_analytics():
    """Comprehensive analytics dashboard with revenue, users, usage, funnel, tools, activity, response times, and geo."""
    from datetime import timedelta

    base_dir = os.path.dirname(os.path.dirname(__file__))
    keys_db = os.path.join(base_dir, "api_keys.db")
    funnel_db = os.path.join(base_dir, "funnel.db")
    tool_usage_db = os.path.join(base_dir, "tool_usage.db")

    now = datetime.utcnow()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    # ── 1. Revenue Card ──────────────────────────────────────────────────────
    rev_total = _query_one(keys_db, "SELECT COALESCE(SUM(total_spent), 0) as v FROM api_keys").get("v", 0)
    rev_today = _query_one(keys_db, "SELECT COALESCE(SUM(total_spent), 0) as v FROM api_keys WHERE date(last_used_at) = date('now')").get("v", 0)
    rev_week = _query_one(keys_db, "SELECT COALESCE(SUM(total_spent), 0) as v FROM api_keys WHERE last_used_at >= ?", (week_ago,)).get("v", 0)
    rev_month = _query_one(keys_db, "SELECT COALESCE(SUM(total_spent), 0) as v FROM api_keys WHERE last_used_at >= ?", (month_ago,)).get("v", 0)

    # ── 2. Users Card ────────────────────────────────────────────────────────
    users_total = _query_one(keys_db, "SELECT COUNT(*) as v FROM api_keys").get("v", 0)
    users_today = _query_one(keys_db, "SELECT COUNT(*) as v FROM api_keys WHERE date(created_at) = date('now')").get("v", 0)
    users_active = _query_one(keys_db, "SELECT COUNT(*) as v FROM api_keys WHERE balance_usd > 0 AND is_active = 1").get("v", 0)

    # ── 3. Usage Card ────────────────────────────────────────────────────────
    usage_total = _query_one(keys_db, "SELECT COALESCE(SUM(call_count), 0) as v FROM api_keys").get("v", 0)
    usage_today = _query_one(tool_usage_db, "SELECT COALESCE(SUM(count), 0) as v FROM tool_usage WHERE date(last_used) = date('now')").get("v", 0)
    usage_week = _query_one(tool_usage_db, "SELECT COALESCE(SUM(count), 0) as v FROM tool_usage WHERE last_used >= ?", (week_ago,)).get("v", 0)
    usage_avg = round(usage_total / users_total, 1) if users_total > 0 else 0

    # ── 4. Conversion Funnel (30d, humans only) ─────────────────────────────
    funnel_stages = ["discover_hit", "catalog_browse", "demo_used", "key_generated", "credits_bought"]
    human_30d = get_funnel_stats(days=30, exclude_bots=True)
    by_type = human_30d.get("by_type", {})
    funnel = []
    first_count = None
    prev = None
    for stage in funnel_stages:
        count = by_type.get(stage, 0)
        step_conv = round(100 * count / prev, 1) if prev and prev > 0 else None
        if first_count is None and count > 0:
            first_count = count
        overall_conv = round(100 * count / first_count, 1) if first_count and first_count > 0 and stage != funnel_stages[0] else None
        funnel.append({"stage": stage, "count": count, "step_pct": step_conv, "overall_pct": overall_conv})
        prev = count if count > 0 else prev

    # ── 5. Top Tools (bar chart data) ────────────────────────────────────────
    top_tools = _query_db(tool_usage_db,
        "SELECT tool_name, SUM(count) as total_calls, MAX(last_used) as last_used FROM tool_usage GROUP BY tool_name ORDER BY total_calls DESC LIMIT 10")
    max_tool_calls = max((t["total_calls"] for t in top_tools), default=1) or 1

    # ── 6. Recent Activity Feed ──────────────────────────────────────────────
    recent_events = _query_db(funnel_db,
        "SELECT event_type, endpoint, ip, created_at, metadata FROM funnel_events WHERE is_bot = 0 ORDER BY id DESC LIMIT 20")

    # ── 7. Response Time Stats ───────────────────────────────────────────────
    try:
        from app import get_response_time_stats
        rt_stats = get_response_time_stats(window_seconds=3600)
    except Exception:
        rt_stats = {"avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "count": 0}

    # ── 8. Geographic / IP Distribution ──────────────────────────────────────
    top_ips = _query_db(funnel_db,
        "SELECT ip, COUNT(*) as cnt FROM funnel_events WHERE is_bot = 0 AND ip != '' GROUP BY ip ORDER BY cnt DESC LIMIT 10")

    # ── Traffic periods ──────────────────────────────────────────────────────
    periods = {"24h": 1, "7d": 7, "30d": 30}
    period_stats = {}
    for label, days in periods.items():
        stats = get_funnel_stats(days=days, exclude_bots=False)
        human_stats = get_funnel_stats(days=days, exclude_bots=True)
        period_stats[label] = {
            "total_events": stats["total_events"],
            "bot_events": stats.get("bot_events", 0),
            "human_events": human_stats["total_events"],
            "unique_ips": human_stats.get("unique_ips", 0),
        }

    # ── JSON mode ────────────────────────────────────────────────────────────
    if request.args.get("format") == "json":
        return jsonify({
            "revenue": {"total": rev_total, "today": rev_today, "week": rev_week, "month": rev_month},
            "users": {"total": users_total, "today": users_today, "active_paying": users_active},
            "usage": {"total": usage_total, "today": usage_today, "week": usage_week, "avg_per_user": usage_avg},
            "funnel_30d": funnel,
            "top_tools": top_tools,
            "recent_events": recent_events,
            "response_times": rt_stats,
            "top_ips": top_ips,
            "periods": period_stats,
        })

    # ── Build HTML Dashboard ─────────────────────────────────────────────────
    def _fmt_usd(v):
        return f"${v:,.2f}" if v else "$0.00"

    def _fmt_num(v):
        return f"{v:,}" if v else "0"

    # Top tools bar chart (CSS only)
    tool_bars = ""
    for t in top_tools:
        pct = round(100 * t["total_calls"] / max_tool_calls)
        tool_bars += (
            f'<div class="bar-row">'
            f'<span class="bar-label">{t["tool_name"]}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>'
            f'<span class="bar-value">{_fmt_num(t["total_calls"])}</span>'
            f'</div>'
        )
    if not tool_bars:
        tool_bars = '<p class="muted">No tool usage recorded yet</p>'

    # Funnel rows
    funnel_html = ""
    stage_colors = {"discover_hit": "#6366f1", "catalog_browse": "#818cf8", "demo_used": "#a78bfa", "key_generated": "#34d399", "credits_bought": "#fbbf24"}
    for f_item in funnel:
        color = stage_colors.get(f_item["stage"], "#888")
        step_str = f'{f_item["step_pct"]}%' if f_item["step_pct"] is not None else "-"
        bar_w = round(100 * f_item["count"] / (first_count or 1)) if first_count else 0
        funnel_html += (
            f'<div class="funnel-row">'
            f'<span class="funnel-label">{f_item["stage"].replace("_", " ").title()}</span>'
            f'<div class="funnel-bar-track"><div class="funnel-bar" style="width:{bar_w}%;background:{color}"></div></div>'
            f'<span class="funnel-count">{_fmt_num(f_item["count"])}</span>'
            f'<span class="funnel-conv">{step_str}</span>'
            f'</div>'
        )

    # Recent activity
    activity_rows = ""
    event_icons = {"key_generated": "&#128273;", "credits_bought": "&#128176;", "402_shown": "&#128274;",
                   "discover_hit": "&#128270;", "demo_used": "&#127918;", "free_tier_exhausted": "&#9888;",
                   "catalog_browse": "&#128218;", "mcp_free_exhausted": "&#9888;"}
    for ev in recent_events:
        icon = event_icons.get(ev["event_type"], "&#8226;")
        ts = ev["created_at"][:16].replace("T", " ")
        activity_rows += (
            f'<div class="activity-item">'
            f'<span class="activity-icon">{icon}</span>'
            f'<span class="activity-type">{ev["event_type"]}</span>'
            f'<span class="activity-detail">{ev.get("endpoint", "")}</span>'
            f'<span class="activity-ip">{ev.get("ip", "")}</span>'
            f'<span class="activity-time">{ts}</span>'
            f'</div>'
        )
    if not activity_rows:
        activity_rows = '<p class="muted">No recent activity</p>'

    # IP distribution
    ip_rows = ""
    for ip_row in top_ips:
        ip_rows += f'<tr><td><code>{ip_row["ip"]}</code></td><td>{_fmt_num(ip_row["cnt"])}</td></tr>'
    if not ip_rows:
        ip_rows = '<tr><td colspan="2" class="muted">No IP data yet</td></tr>'

    # Traffic period rows
    period_rows = ""
    for label, data in period_stats.items():
        period_rows += (
            f'<tr><td>{label}</td><td>{_fmt_num(data["total_events"])}</td>'
            f'<td style="color:#f87171">{_fmt_num(data["bot_events"])}</td>'
            f'<td style="color:#34d399">{_fmt_num(data["human_events"])}</td>'
            f'<td>{_fmt_num(data["unique_ips"])}</td></tr>'
        )

    admin_token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.headers.get("X-Admin-Key", "")

    # Quick actions JS
    actions_js = (
        "function adminAction(url, method) {"
        "  if (!confirm('Are you sure?')) return;"
        "  fetch(url, {method: method || 'POST', headers: {'Authorization': 'Bearer ' + document.querySelector('meta[name=admin-token]').content}})"
        "  .then(function(r) { return r.json(); }).then(function(d) { alert(d.message || JSON.stringify(d)); location.reload(); })"
        "  .catch(function(e) { alert('Error: ' + e); });"
        "}"
    )

    activation_rate = round(100 * users_active / users_total, 1) if users_total > 0 else 0

    html = (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="admin-token" content="{admin_token}">'
        '<meta http-equiv="refresh" content="60">'
        '<title>Admin Dashboard - AiPayGen</title>'
        '<style>'
        '*{box-sizing:border-box;margin:0;padding:0}'
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0a0a0a;color:#e8e8e8;padding:24px 16px}'
        '.wrap{max-width:1200px;margin:0 auto}'
        'h1{font-size:1.6rem;margin-bottom:4px;color:#fff}'
        '.sub{color:#888;font-size:0.82rem;margin-bottom:20px}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:20px}'
        '.card{background:#141414;border:1px solid #2a2a2a;border-radius:14px;padding:20px}'
        '.card-wide{grid-column:1/-1}'
        '.card-half{grid-column:span 2}'
        'h2{font-size:1rem;margin:0 0 14px;color:#a5b4fc;font-weight:600}'
        '.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}'
        '.stat{text-align:center}'
        '.stat-value{font-size:1.5rem;font-weight:700;color:#fff}'
        '.stat-value.green{color:#34d399}'
        '.stat-value.blue{color:#6366f1}'
        '.stat-value.amber{color:#fbbf24}'
        '.stat-label{font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-top:2px}'
        'table{width:100%;border-collapse:collapse;font-size:0.8rem}'
        'th,td{padding:7px 10px;text-align:left;border-bottom:1px solid #1e1e1e}'
        'th{color:#666;font-weight:600;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.5px}'
        'code{background:#1e1e1e;padding:2px 6px;border-radius:4px;font-size:0.78rem;color:#a5b4fc}'
        '.muted{color:#555;font-size:0.82rem}'
        'a{color:#6366f1;text-decoration:none}'
        'a:hover{text-decoration:underline}'
        '.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:0.8rem}'
        '.bar-label{width:140px;text-align:right;color:#ccc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0}'
        '.bar-track{flex:1;height:20px;background:#1e1e1e;border-radius:4px;overflow:hidden}'
        '.bar-fill{height:100%;background:linear-gradient(90deg,#6366f1,#818cf8);border-radius:4px;transition:width 0.3s}'
        '.bar-value{width:50px;color:#888;font-size:0.75rem;flex-shrink:0}'
        '.funnel-row{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:0.8rem}'
        '.funnel-label{width:120px;color:#ccc;flex-shrink:0;font-size:0.78rem}'
        '.funnel-bar-track{flex:1;height:18px;background:#1e1e1e;border-radius:4px;overflow:hidden}'
        '.funnel-bar{height:100%;border-radius:4px;transition:width 0.3s}'
        '.funnel-count{width:50px;color:#fff;font-weight:600;flex-shrink:0;text-align:right;font-size:0.78rem}'
        '.funnel-conv{width:50px;color:#888;font-size:0.72rem;flex-shrink:0;text-align:right}'
        '.activity-item{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #1a1a1a;font-size:0.78rem}'
        '.activity-icon{font-size:0.9rem;width:20px;text-align:center;flex-shrink:0}'
        '.activity-type{color:#a5b4fc;font-weight:600;width:150px;flex-shrink:0}'
        '.activity-detail{color:#888;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'
        '.activity-ip{color:#555;width:110px;flex-shrink:0;font-family:monospace;font-size:0.72rem}'
        '.activity-time{color:#444;width:120px;flex-shrink:0;text-align:right;font-size:0.72rem}'
        '.actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}'
        '.btn{padding:8px 16px;border:1px solid #333;border-radius:8px;background:#1a1a1a;color:#e8e8e8;cursor:pointer;font-size:0.8rem;transition:background 0.2s;text-decoration:none}'
        '.btn:hover{background:#2a2a2a}'
        '.btn-danger{border-color:#7f1d1d;color:#fca5a5}.btn-danger:hover{background:#7f1d1d}'
        '.btn-green{border-color:#064e3b;color:#6ee7b7}.btn-green:hover{background:#064e3b}'
        '.btn-blue{border-color:#1e3a5f;color:#93c5fd}.btn-blue:hover{background:#1e3a5f}'
        '.rt-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}'
        '.rt-item{text-align:center;padding:10px;background:#1a1a1a;border-radius:8px}'
        '.rt-val{font-size:1.2rem;font-weight:700;color:#fff}'
        '.rt-label{font-size:0.68rem;color:#888;margin-top:2px;text-transform:uppercase}'
        '@media(max-width:768px){'
        '  .grid{grid-template-columns:1fr}'
        '  .card-half{grid-column:span 1}'
        '  .bar-label,.funnel-label{width:80px;font-size:0.7rem}'
        '  .activity-ip,.activity-detail{display:none}'
        '  .rt-grid{grid-template-columns:repeat(2,1fr)}'
        '}'
        '</style></head><body>'
        '<div class="wrap">'
        '<h1>Admin Dashboard</h1>'
        f'<p class="sub">Auto-refreshes every 60s &middot; <a href="?format=json">JSON API</a> &middot; Updated {now.strftime("%H:%M:%S UTC")}</p>'
        '<!-- Quick Actions -->'
        '<div class="actions">'
        '  <button class="btn btn-green" onclick="adminAction(\'/admin/clear-cache\',\'POST\')">Clear Cache</button>'
        '  <button class="btn btn-danger" onclick="adminAction(\'/admin/restart\',\'POST\')">Restart Workers</button>'
        '  <button class="btn" onclick="adminAction(\'/admin/run?job=maintenance\',\'POST\')">Run Maintenance</button>'
        '  <a class="btn btn-blue" href="/admin/export">Export Data (CSV)</a>'
        '</div>'
        '<!-- Row 1: KPI Cards -->'
        '<div class="grid">'
        '  <div class="card">'
        '    <h2>Revenue</h2>'
        '    <div class="stat-grid">'
        f'      <div class="stat"><div class="stat-value green">{_fmt_usd(rev_total)}</div><div class="stat-label">Total</div></div>'
        f'      <div class="stat"><div class="stat-value">{_fmt_usd(rev_today)}</div><div class="stat-label">Today</div></div>'
        f'      <div class="stat"><div class="stat-value">{_fmt_usd(rev_week)}</div><div class="stat-label">This Week</div></div>'
        f'      <div class="stat"><div class="stat-value">{_fmt_usd(rev_month)}</div><div class="stat-label">This Month</div></div>'
        '    </div>'
        '  </div>'
        '  <div class="card">'
        '    <h2>Users</h2>'
        '    <div class="stat-grid">'
        f'      <div class="stat"><div class="stat-value blue">{_fmt_num(users_total)}</div><div class="stat-label">Total Keys</div></div>'
        f'      <div class="stat"><div class="stat-value">{_fmt_num(users_today)}</div><div class="stat-label">Created Today</div></div>'
        f'      <div class="stat"><div class="stat-value green">{_fmt_num(users_active)}</div><div class="stat-label">Active (Balance &gt; 0)</div></div>'
        f'      <div class="stat"><div class="stat-value">{activation_rate}%</div><div class="stat-label">Activation Rate</div></div>'
        '    </div>'
        '  </div>'
        '  <div class="card">'
        '    <h2>Usage</h2>'
        '    <div class="stat-grid">'
        f'      <div class="stat"><div class="stat-value amber">{_fmt_num(usage_total)}</div><div class="stat-label">Total Calls</div></div>'
        f'      <div class="stat"><div class="stat-value">{_fmt_num(usage_today)}</div><div class="stat-label">Today</div></div>'
        f'      <div class="stat"><div class="stat-value">{_fmt_num(usage_week)}</div><div class="stat-label">This Week</div></div>'
        f'      <div class="stat"><div class="stat-value">{usage_avg}</div><div class="stat-label">Avg/User</div></div>'
        '    </div>'
        '  </div>'
        '  <div class="card">'
        '    <h2>Response Times (1h)</h2>'
        '    <div class="rt-grid">'
        f'      <div class="rt-item"><div class="rt-val">{rt_stats["avg_ms"]:.0f}ms</div><div class="rt-label">Average</div></div>'
        f'      <div class="rt-item"><div class="rt-val">{rt_stats["p50_ms"]:.0f}ms</div><div class="rt-label">P50</div></div>'
        f'      <div class="rt-item"><div class="rt-val">{rt_stats["p95_ms"]:.0f}ms</div><div class="rt-label">P95</div></div>'
        f'      <div class="rt-item"><div class="rt-val">{rt_stats["p99_ms"]:.0f}ms</div><div class="rt-label">P99</div></div>'
        '    </div>'
        f'    <p class="muted" style="margin-top:8px;text-align:center;font-size:0.72rem">{_fmt_num(rt_stats["count"])} requests tracked</p>'
        '  </div>'
        '</div>'
        '<!-- Row 2: Charts -->'
        '<div class="grid">'
        '  <div class="card card-half">'
        '    <h2>Top 10 Tools by Usage</h2>'
        f'    {tool_bars}'
        '  </div>'
        '  <div class="card">'
        '    <h2>Conversion Funnel (30d)</h2>'
        f'    {funnel_html}'
        '  </div>'
        '</div>'
        '<!-- Row 3: Activity + Traffic + IPs -->'
        '<div class="grid">'
        '  <div class="card card-half">'
        '    <h2>Recent Activity (Last 20 events)</h2>'
        f'    {activity_rows}'
        '  </div>'
        '  <div class="card">'
        '    <h2>Traffic Overview</h2>'
        '    <table>'
        '      <thead><tr><th>Period</th><th>Total</th><th>Bot</th><th>Human</th><th>IPs</th></tr></thead>'
        f'      <tbody>{period_rows}</tbody>'
        '    </table>'
        '  </div>'
        '</div>'
        '<div class="grid">'
        '  <div class="card">'
        '    <h2>Top IPs (non-bot)</h2>'
        '    <table>'
        '      <thead><tr><th>IP Address</th><th>Events</th></tr></thead>'
        f'      <tbody>{ip_rows}</tbody>'
        '    </table>'
        '  </div>'
        '</div>'
        '<p style="text-align:center;margin-top:20px;font-size:0.72rem;color:#444">'
        '  <a href="/admin/funnel" style="color:#555">Funnel dashboard</a> &middot;'
        '  <a href="/stats" style="color:#555">Payment stats</a> &middot;'
        '  <a href="/status" style="color:#555">Status</a> &middot;'
        '  <a href="/admin/export" style="color:#555">Export CSV</a>'
        '</p>'
        '</div>'
        f'<script>{actions_js}</script>'
        '</body></html>'
    )
    return html, 200, {"Content-Type": "text/html"}
