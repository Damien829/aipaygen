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

import trading_engine
import backtesting
import a2a_engine

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

*Marketplace*
/status — Server health & stats
/agents — Top agents
/leaderboard — Rankings
/categories — All categories
/revenue — Revenue breakdown

*Trading*
/deploy <type> — Deploy strategy (momentum, mean\_reversion, sentiment, dca)
/trade <id> <pair> <side> <qty> — Paper trade
/backtest <type> <pair> [days] — Run backtest
/portfolio [strategy\_id] — Portfolio stats

*Network*
/a2a — A2A commerce stats
/alerts — Toggle alert notifications

*System*
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


# ── Alert flag ────────────────────────────────────────────────────────────────
ALERTS_FLAG_FILE = os.path.join(DB_DIR, ".telegram_alerts_enabled")

def _alerts_enabled():
    return os.path.exists(ALERTS_FLAG_FILE)

def _toggle_alerts():
    if _alerts_enabled():
        os.remove(ALERTS_FLAG_FILE)
        return False
    with open(ALERTS_FLAG_FILE, "w") as f:
        f.write("1")
    return True


def send_alert(message: str):
    """Send an alert to the bot owner. Called by external modules."""
    _load_owner()
    if OWNER_ID and _alerts_enabled():
        send(OWNER_ID, f"*ALERT*\n{message}")


# ── Trading Commands ──────────────────────────────────────────────────────────

VALID_STRATEGY_TYPES = {"momentum", "mean_reversion", "sentiment", "dca"}

def cmd_deploy(chat_id, text):
    parts = text.split()
    if len(parts) < 2:
        send(chat_id, "Usage: `/deploy <strategy_type>`\nTypes: momentum, mean\\_reversion, sentiment, dca")
        return
    stype = parts[1].lower()
    if stype not in VALID_STRATEGY_TYPES:
        send(chat_id, f"Invalid type `{stype}`. Choose: momentum, mean\\_reversion, sentiment, dca")
        return
    try:
        result = trading_engine.create_strategy(
            agent_id="telegram_bot",
            name=f"tg_{stype}",
            strategy_type=stype,
        )
        portfolio = trading_engine.create_portfolio(
            user_id="telegram_owner",
            strategy_id=result["strategy_id"],
        )
        send(chat_id, f"""*Strategy Deployed*

Type: `{stype}`
Strategy ID: `{result['strategy_id']}`
Status: `{result['status']}`
Mode: `{result['mode']}`
Portfolio: `{portfolio['portfolio_id']}`
Balance: `${portfolio['balance']:.2f}`""")
    except Exception as e:
        send(chat_id, f"Deploy failed: {e}")


def cmd_trade(chat_id, text):
    parts = text.split()
    if len(parts) < 5:
        send(chat_id, "Usage: `/trade <strategy_id> <pair> <side> <quantity>`\nSide: long or short")
        return
    strategy_id, pair, side, qty_str = parts[1], parts[2].upper(), parts[3].lower(), parts[4]
    if side not in ("long", "short"):
        send(chat_id, "Side must be `long` or `short`")
        return
    try:
        qty = float(qty_str)
    except ValueError:
        send(chat_id, "Quantity must be a number")
        return
    try:
        result = trading_engine.open_trade(
            strategy_id=strategy_id,
            agent_id="telegram_bot",
            pair=pair,
            side=side,
            entry_price=0.0,  # paper trade — engine records at market
            quantity=qty,
            exchange="paper",
            entry_reason="telegram_manual",
        )
        if "error" in result:
            send(chat_id, f"Trade error: {result['error']}")
            return
        send(chat_id, f"""*Trade Opened*

Trade ID: `{result['trade_id']}`
Pair: `{result['pair']}`
Side: `{result['side']}`
Quantity: `{result['quantity']}`
Status: `{result['status']}`""")
    except Exception as e:
        send(chat_id, f"Trade failed: {e}")


def cmd_backtest(chat_id, text):
    parts = text.split()
    if len(parts) < 3:
        send(chat_id, "Usage: `/backtest <strategy_type> <pair> [days]`\nExample: `/backtest momentum BTC/USD 30`")
        return
    stype = parts[1].lower()
    pair = parts[2].upper()
    days = 30
    if len(parts) >= 4:
        try:
            days = int(parts[3])
        except ValueError:
            send(chat_id, "Days must be a number")
            return
    if stype not in VALID_STRATEGY_TYPES:
        send(chat_id, f"Invalid type `{stype}`. Choose: momentum, mean\\_reversion, sentiment, dca")
        return
    try:
        send(chat_id, f"Running backtest: `{stype}` on `{pair}` for {days}d...")
        result = backtesting.run_backtest(
            strategy_type=stype,
            config={},
            pair=pair,
            days=days,
        )
        if "error" in result:
            send(chat_id, f"Backtest error: {result['error']}")
            return
        send(chat_id, f"""*Backtest Results*

Strategy: `{stype}`
Pair: `{pair}` | Days: `{days}`

P&L: `{result['total_pnl_pct']:.2f}%` (${result['total_pnl']:.2f})
Final Balance: `${result['final_balance']:.2f}`
Win Rate: `{result['win_rate']}%`
Trades: `{result['total_trades']}` ({result['winning_trades']}W / {result['losing_trades']}L)
Sharpe: `{result['sharpe_ratio']}`
Max Drawdown: `{result['max_drawdown_pct']:.2f}%`
Avg Trade: `${result['avg_trade_pnl']:.2f}`
Duration: `{result['duration_ms']}ms`""")
    except Exception as e:
        send(chat_id, f"Backtest failed: {e}")


def cmd_portfolio(chat_id, text):
    parts = text.split()
    try:
        if len(parts) >= 2:
            strategy_id = parts[1]
            p = trading_engine.get_portfolio(user_id="telegram_owner", strategy_id=strategy_id)
            if not p:
                send(chat_id, f"No portfolio found for strategy `{strategy_id}`")
                return
            send(chat_id, f"""*Portfolio*

Strategy: `{p.get('strategy_id', '?')}`
Balance: `${p['balance']:.2f}` (initial ${p['initial_balance']:.2f})
P&L: `{p.get('total_pnl_pct', 0):.2f}%`
Win Rate: `{p.get('win_rate', 0)}%`
Trades: `{p.get('total_trades', 0)}`
Max Drawdown: `{p.get('max_drawdown_pct', 0):.2f}%`
Sharpe Proxy: `{p.get('sharpe_proxy', 0)}`
Status: `{p.get('status', '?')}`""")
        else:
            portfolios = trading_engine.list_portfolios(user_id="telegram_owner")
            if not portfolios:
                send(chat_id, "No portfolios. Deploy a strategy first with /deploy")
                return
            lines = ["*All Portfolios*\n"]
            for p in portfolios:
                pnl = p.get("total_pnl_pct", 0)
                lines.append(
                    f"  `{p['strategy_id'][:8]}...` — "
                    f"${p['balance']:.2f} | {pnl:.1f}% | "
                    f"{p.get('total_trades', 0)} trades"
                )
            send(chat_id, "\n".join(lines))
    except Exception as e:
        send(chat_id, f"Portfolio error: {e}")


def cmd_alerts(chat_id):
    enabled = _toggle_alerts()
    state = "ON" if enabled else "OFF"
    send(chat_id, f"Alerts toggled *{state}*")


def cmd_a2a(chat_id):
    try:
        stats = a2a_engine.a2a_stats()
        send(chat_id, f"""*A2A Commerce Stats*

Live Agents: `{stats['live_agents']}`
Open RFQs: `{stats['open_rfqs']}`
Active Contracts: `{stats['active_contracts']}`

*Transactions*
Total: `{stats['total_transactions']}` (${stats['total_volume_usd']:.2f})
24h: `{stats['transactions_24h']}` (${stats['volume_24h_usd']:.2f})""")
    except Exception as e:
        send(chat_id, f"A2A error: {e}")


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
    "/deploy": lambda cid, uid, txt: cmd_deploy(cid, txt),
    "/trade": lambda cid, uid, txt: cmd_trade(cid, txt),
    "/backtest": lambda cid, uid, txt: cmd_backtest(cid, txt),
    "/portfolio": lambda cid, uid, txt: cmd_portfolio(cid, txt),
    "/alerts": lambda cid, uid, _: cmd_alerts(cid),
    "/a2a": lambda cid, uid, _: cmd_a2a(cid),
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
