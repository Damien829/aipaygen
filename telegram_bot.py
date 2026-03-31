#!/usr/bin/env python3
"""AiPayGen Marketplace Telegram Bot — manage your marketplace from your phone."""
import json
import os
import signal
import subprocess
import sys
import time
import requests
import sqlite3
from datetime import datetime, timezone

TOKEN_FILE = os.path.expanduser("~/.secrets/telegram_bot_token")
TOKEN = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else os.getenv("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"
BASE = "http://127.0.0.1:5001"
DB_DIR = os.path.dirname(os.path.abspath(__file__))

# Only allow your Telegram user ID (set on first /start)
OWNER_FILE = os.path.join(DB_DIR, ".telegram_owner_id")
OWNER_ID = None

def _load_owner():
    global OWNER_ID
    if os.path.exists(OWNER_FILE):
        OWNER_ID = int(open(OWNER_FILE).read().strip())

def _save_owner(uid):
    global OWNER_ID
    OWNER_ID = uid
    with open(OWNER_FILE, "w") as f:
        f.write(str(uid))

def _is_owner(uid):
    return OWNER_ID is None or uid == OWNER_ID

def send(chat_id, text, parse_mode="Markdown"):
    """Send a message, splitting if too long."""
    for i in range(0, len(text), 4000):
        try:
            requests.post(f"{API}/sendMessage", json={
                "chat_id": chat_id, "text": text[i:i+4000], "parse_mode": parse_mode
            }, timeout=10)
        except Exception:
            requests.post(f"{API}/sendMessage", json={
                "chat_id": chat_id, "text": text[i:i+4000]
            }, timeout=10)


def cmd_start(chat_id, uid):
    if OWNER_ID is None:
        _save_owner(uid)
    send(chat_id, """*AiPayGen Agent Market*

Your marketplace, in your pocket.

/status — Server health & stats
/agents — Top agents
/leaderboard — Rankings
/categories — All categories
/revenue — Revenue breakdown
/restart — Restart server
/logs — Recent server logs
/help — This message""")


def cmd_status(chat_id):
    try:
        h = requests.get(f"{BASE}/health", timeout=5).json()
        status = h.get("status", "unknown")
        uptime = h.get("uptime_human", "unknown")
    except Exception:
        send(chat_id, "Server is DOWN")
        return

    try:
        cats = requests.get(f"{BASE}/marketplace/categories", timeout=5).json()
        cat_data = cats.get("categories", {})
        total_agents = sum(cat_data.values())
        total_cats = len(cat_data)
    except Exception:
        total_agents = "?"
        total_cats = "?"

    try:
        lb = requests.get(f"{BASE}/marketplace/leaderboard?limit=1", timeout=5).json()
        top = lb.get("leaders", [{}])[0].get("name", "none") if lb.get("leaders") else "none"
    except Exception:
        top = "?"

    send(chat_id, f"""*Server Status*

Status: `{status}`
Uptime: `{uptime}`
Agents: `{total_agents}`
Categories: `{total_cats}`
Top Agent: `{top}`""")


def cmd_agents(chat_id):
    try:
        r = requests.get(f"{BASE}/marketplace?sort=popular&per_page=10", timeout=5).json()
        agents = r.get("agents", r.get("listings", []))
    except Exception:
        send(chat_id, "Could not fetch agents")
        return

    if not agents:
        send(chat_id, "No agents listed yet.")
        return

    lines = ["*Top Agents*\n"]
    for i, a in enumerate(agents[:10]):
        name = a.get("name", "?")
        cat = a.get("category", "?")
        calls = a.get("call_count", 0)
        price = a.get("price_usd", 0)
        rating = a.get("avg_rating", 0)
        stars = "+" * int(rating) if rating > 0 else "-"
        lines.append(f"{i+1}. *{name}* [{cat}]\n   ${price:.2f}/call | {calls} calls | {stars}")

    send(chat_id, "\n".join(lines))


def cmd_leaderboard(chat_id):
    try:
        r = requests.get(f"{BASE}/marketplace/leaderboard?limit=10", timeout=5).json()
        leaders = r.get("leaders", [])
    except Exception:
        send(chat_id, "Could not fetch leaderboard")
        return

    if not leaders:
        send(chat_id, "No agents on leaderboard yet.")
        return

    lines = ["*Leaderboard*\n"]
    for i, a in enumerate(leaders):
        name = a.get("name", "?")
        calls = a.get("call_count", 0)
        rev = a.get("total_revenue", 0)
        lines.append(f"{i+1}. *{name}* — {calls} calls, ${rev:.2f} rev")

    send(chat_id, "\n".join(lines))


def cmd_categories(chat_id):
    try:
        r = requests.get(f"{BASE}/marketplace/categories", timeout=5).json()
        cats = r.get("categories", {})
    except Exception:
        send(chat_id, "Could not fetch categories")
        return

    lines = ["*Categories*\n"]
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        lines.append(f"  `{cat}` — {count} agents")

    lines.append(f"\n*Total: {sum(cats.values())} agents*")
    send(chat_id, "\n".join(lines))


def cmd_revenue(chat_id):
    try:
        db = sqlite3.connect(os.path.join(DB_DIR, "billing_audit.db"))
        db.row_factory = sqlite3.Row

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = db.execute(
            "SELECT SUM(amount_usd) as total, COUNT(*) as calls FROM billing_audit WHERE event_type='deduction' AND date(created_at)=?",
            (today,)
        ).fetchone()
        today_rev = row["total"] or 0
        today_calls = row["calls"] or 0

        row7 = db.execute(
            "SELECT SUM(amount_usd) as total, COUNT(*) as calls FROM billing_audit WHERE event_type='deduction' AND created_at > date('now', '-7 days')"
        ).fetchone()
        week_rev = row7["total"] or 0
        week_calls = row7["calls"] or 0

        keys = db.execute("SELECT COUNT(*) FROM billing_audit WHERE event_type='key_generated'").fetchone()[0]

        # Real API cost
        try:
            cdb = sqlite3.connect(os.path.join(DB_DIR, "discovery_engine.db"))
            cost_row = cdb.execute("SELECT SUM(cost_usd) FROM cost_tracking WHERE date >= date('now', '-7 days')").fetchone()
            api_cost = cost_row[0] or 0
        except Exception:
            api_cost = 0

        send(chat_id, f"""*Revenue Dashboard*

*Today*
Revenue: `${today_rev:.2f}`
API Calls: `{today_calls}`

*Last 7 Days*
Revenue: `${week_rev:.2f}`
API Calls: `{week_calls}`

*All Time*
Keys Generated: `{keys}`

*Your API Cost (7d)*
Anthropic: `${api_cost:.4f}`
Margin: `${week_rev - api_cost:.2f}`""")
        db.close()
    except Exception as e:
        send(chat_id, f"Error: {e}")


def cmd_restart(chat_id):
    send(chat_id, "Restarting server...")
    try:
        subprocess.run(["pkill", "-HUP", "-f", "gunicorn.*master"], timeout=5)
        time.sleep(3)
        r = requests.get(f"{BASE}/health", timeout=10)
        if r.status_code == 200:
            send(chat_id, "Server restarted. Status: `healthy`")
        else:
            send(chat_id, f"Server responded with {r.status_code}")
    except Exception as e:
        send(chat_id, f"Restart failed: {e}")


def cmd_logs(chat_id):
    try:
        log_file = os.path.join(DB_DIR, "gunicorn.error.log")
        if not os.path.exists(log_file):
            log_file = os.path.join(DB_DIR, "error.log")
        if os.path.exists(log_file):
            lines = open(log_file).readlines()[-15:]
            send(chat_id, "*Recent Logs*\n```\n" + "".join(lines) + "```")
        else:
            send(chat_id, "No log file found")
    except Exception as e:
        send(chat_id, f"Error: {e}")


COMMANDS = {
    "/start": lambda cid, uid, _: cmd_start(cid, uid),
    "/help": lambda cid, uid, _: cmd_start(cid, uid),
    "/status": lambda cid, uid, _: cmd_status(cid),
    "/agents": lambda cid, uid, _: cmd_agents(cid),
    "/leaderboard": lambda cid, uid, _: cmd_leaderboard(cid),
    "/categories": lambda cid, uid, _: cmd_categories(cid),
    "/revenue": lambda cid, uid, _: cmd_revenue(cid),
    "/restart": lambda cid, uid, _: cmd_restart(cid),
    "/logs": lambda cid, uid, _: cmd_logs(cid),
}


def poll():
    """Long-poll for updates."""
    _load_owner()
    offset = 0
    print(f"[AiPayGen Bot] Started. Owner: {OWNER_ID or 'first user to /start'}")

    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={
                "offset": offset, "timeout": 30
            }, timeout=35)
            updates = r.json().get("result", [])

            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = msg.get("chat", {}).get("id")
                uid = msg.get("from", {}).get("id")

                if not chat_id or not text:
                    continue

                if not _is_owner(uid):
                    send(chat_id, "Unauthorized. This bot is private.")
                    continue

                cmd = text.split()[0].lower().split("@")[0]
                if cmd in COMMANDS:
                    try:
                        COMMANDS[cmd](chat_id, uid, text)
                    except Exception as e:
                        send(chat_id, f"Error: {e}")
                else:
                    send(chat_id, f"Unknown command. Try /help")

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"[AiPayGen Bot] Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    if not TOKEN:
        print("No token found. Set TELEGRAM_BOT_TOKEN or create ~/.secrets/telegram_bot_token")
        sys.exit(1)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    poll()
