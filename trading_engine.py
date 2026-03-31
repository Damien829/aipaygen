"""Trading engine — strategy management, paper trading, P&L tracking."""
import sqlite3
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "trading.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def init_trading_db():
    with _conn() as c:
        # Trading strategies — agent configs
        c.execute("""CREATE TABLE IF NOT EXISTS trading_strategies (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            listing_id TEXT DEFAULT '',
            name TEXT NOT NULL,
            strategy_type TEXT NOT NULL DEFAULT 'custom',
            config TEXT NOT NULL DEFAULT '{}',
            pairs TEXT NOT NULL DEFAULT '[]',
            exchange TEXT NOT NULL DEFAULT 'paper',
            mode TEXT NOT NULL DEFAULT 'paper',
            status TEXT NOT NULL DEFAULT 'paused',
            max_position_usd REAL DEFAULT 100.0,
            stop_loss_pct REAL DEFAULT 5.0,
            take_profit_pct REAL DEFAULT 10.0,
            daily_loss_limit REAL DEFAULT 50.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_strat_agent ON trading_strategies(agent_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_strat_status ON trading_strategies(status)")

        # Trades — executed trade history
        c.execute("""CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity REAL NOT NULL,
            pnl REAL DEFAULT 0.0,
            pnl_pct REAL DEFAULT 0.0,
            fees REAL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'open',
            exchange TEXT NOT NULL DEFAULT 'paper',
            entry_reason TEXT DEFAULT '',
            exit_reason TEXT DEFAULT '',
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            duration_seconds INTEGER DEFAULT 0,
            FOREIGN KEY (strategy_id) REFERENCES trading_strategies(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_trades_strat ON trades(strategy_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades(agent_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_trades_pair ON trades(pair)")

        # Portfolios — user's portfolio per strategy
        c.execute("""CREATE TABLE IF NOT EXISTS portfolios (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            initial_balance REAL NOT NULL DEFAULT 10000.0,
            balance REAL NOT NULL DEFAULT 10000.0,
            total_pnl REAL DEFAULT 0.0,
            total_pnl_pct REAL DEFAULT 0.0,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            max_drawdown_pct REAL DEFAULT 0.0,
            peak_balance REAL DEFAULT 10000.0,
            active_positions TEXT DEFAULT '[]',
            mode TEXT NOT NULL DEFAULT 'paper',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (strategy_id) REFERENCES trading_strategies(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_port_user ON portfolios(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_port_strat ON portfolios(strategy_id)")

        # Copy subscriptions
        c.execute("""CREATE TABLE IF NOT EXISTS copy_subscriptions (
            id TEXT PRIMARY KEY,
            subscriber_id TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            sizing_multiplier REAL DEFAULT 1.0,
            max_position_usd REAL DEFAULT 100.0,
            auto_execute INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            FOREIGN KEY (strategy_id) REFERENCES trading_strategies(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_copy_sub ON copy_subscriptions(subscriber_id)")

        # Performance snapshots — for charts
        c.execute("""CREATE TABLE IF NOT EXISTS performance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            balance REAL NOT NULL,
            pnl REAL NOT NULL,
            pnl_pct REAL NOT NULL,
            open_positions INTEGER DEFAULT 0,
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (strategy_id) REFERENCES trading_strategies(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_perf_strat ON performance_snapshots(strategy_id)")


# ── Strategy Templates ────────────────────────────────────────────────────────

STRATEGY_TEMPLATES = {
    "momentum": {
        "name": "Momentum",
        "description": "Buy when price crosses above moving average, sell when it crosses below",
        "config": {
            "indicator": "sma",
            "fast_period": 10,
            "slow_period": 30,
            "entry_threshold": 0.02,
            "exit_threshold": -0.01,
        },
        "default_pairs": ["BTC/USD", "ETH/USD", "SOL/USD"],
    },
    "mean_reversion": {
        "name": "Mean Reversion",
        "description": "Buy oversold, sell overbought using RSI and Bollinger Bands",
        "config": {
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "bb_period": 20,
            "bb_std": 2.0,
        },
        "default_pairs": ["BTC/USD", "ETH/USD"],
    },
    "sentiment": {
        "name": "Sentiment Trading",
        "description": "LLM-powered analysis of social media and news for trade signals",
        "config": {
            "sources": ["twitter", "reddit", "news"],
            "sentiment_threshold": 0.7,
            "confidence_min": 0.6,
            "lookback_hours": 24,
        },
        "default_pairs": ["BTC/USD", "ETH/USD", "SOL/USD"],
    },
    "arbitrage": {
        "name": "Cross-Exchange Arbitrage",
        "description": "Detect and exploit price differences across exchanges",
        "config": {
            "min_spread_pct": 0.5,
            "max_execution_ms": 5000,
            "exchanges": ["uniswap", "raydium"],
        },
        "default_pairs": ["ETH/USDC", "SOL/USDC"],
    },
    "dca": {
        "name": "Dollar Cost Average",
        "description": "Automatically buy fixed amounts at regular intervals",
        "config": {
            "interval_hours": 24,
            "amount_usd": 10.0,
            "max_total_usd": 1000.0,
        },
        "default_pairs": ["BTC/USD", "ETH/USD"],
    },
}


# ── Strategy CRUD ─────────────────────────────────────────────────────────────

def create_strategy(agent_id: str, name: str, strategy_type: str = "custom",
                    config: dict = None, pairs: list = None,
                    exchange: str = "paper", mode: str = "paper",
                    listing_id: str = "",
                    max_position_usd: float = 100.0,
                    stop_loss_pct: float = 5.0,
                    take_profit_pct: float = 10.0,
                    daily_loss_limit: float = 50.0) -> dict:
    """Create a new trading strategy."""
    now = datetime.now(timezone.utc).isoformat()
    sid = str(uuid.uuid4())

    # Use template defaults if strategy_type matches
    template = STRATEGY_TEMPLATES.get(strategy_type)
    if template and not config:
        config = template["config"]
    if template and not pairs:
        pairs = template["default_pairs"]

    with _conn() as c:
        c.execute("""INSERT INTO trading_strategies
            (id, agent_id, listing_id, name, strategy_type, config, pairs, exchange,
             mode, status, max_position_usd, stop_loss_pct, take_profit_pct,
             daily_loss_limit, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, agent_id, listing_id, name, strategy_type,
             json.dumps(config or {}), json.dumps(pairs or []),
             exchange, mode, "paused", max_position_usd, stop_loss_pct,
             take_profit_pct, daily_loss_limit, now, now))

    return {"strategy_id": sid, "name": name, "status": "paused", "mode": mode}


def get_strategy(strategy_id: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM trading_strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d.get("config") or "{}")
    d["pairs"] = json.loads(d.get("pairs") or "[]")
    return d


def list_strategies(agent_id: str = None, status: str = None) -> list:
    conditions = []
    params = []
    if agent_id:
        conditions.append("agent_id = ?")
        params.append(agent_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = " AND ".join(conditions) if conditions else "1=1"
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM trading_strategies WHERE {where} ORDER BY created_at DESC", params).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d.get("config") or "{}")
        d["pairs"] = json.loads(d.get("pairs") or "[]")
        results.append(d)
    return results


def update_strategy_status(strategy_id: str, status: str) -> bool:
    """Update strategy status: active, paused, stopped."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute("UPDATE trading_strategies SET status = ?, updated_at = ? WHERE id = ?",
                        (status, now, strategy_id))
    return cur.rowcount > 0


# ── Trade Execution ───────────────────────────────────────────────────────────

def open_trade(strategy_id: str, agent_id: str, pair: str, side: str,
               entry_price: float, quantity: float, exchange: str = "paper",
               entry_reason: str = "") -> dict:
    """Open a new trade position."""
    now = datetime.now(timezone.utc).isoformat()
    tid = str(uuid.uuid4())
    with _conn() as c:
        c.execute("""INSERT INTO trades
            (id, strategy_id, agent_id, pair, side, entry_price, quantity,
             status, exchange, entry_reason, opened_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, strategy_id, agent_id, pair, side, entry_price, quantity,
             "open", exchange, entry_reason, now))
    return {"trade_id": tid, "pair": pair, "side": side, "entry_price": entry_price,
            "quantity": quantity, "status": "open"}


def close_trade(trade_id: str, exit_price: float, exit_reason: str = "") -> dict:
    """Close a trade and calculate P&L."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        trade = c.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not trade:
            return {"error": "trade not found"}
        trade = dict(trade)

        entry = trade["entry_price"]
        qty = trade["quantity"]
        side = trade["side"]

        if side == "long":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        pnl_pct = (pnl / (entry * qty)) * 100 if entry * qty > 0 else 0

        opened = datetime.fromisoformat(trade["opened_at"])
        closed = datetime.fromisoformat(now)
        duration = int((closed - opened).total_seconds())

        c.execute("""UPDATE trades SET exit_price = ?, pnl = ?, pnl_pct = ?,
                     status = 'closed', exit_reason = ?, closed_at = ?,
                     duration_seconds = ? WHERE id = ?""",
                  (exit_price, round(pnl, 4), round(pnl_pct, 2),
                   exit_reason, now, duration, trade_id))

        # Update portfolio
        _update_portfolio_from_trade(c, trade["strategy_id"], pnl, pnl > 0)

    return {"trade_id": trade_id, "pnl": round(pnl, 4), "pnl_pct": round(pnl_pct, 2),
            "duration_seconds": duration, "status": "closed"}


def _update_portfolio_from_trade(cursor, strategy_id: str, pnl: float, is_win: bool):
    """Update portfolio stats after a trade closes."""
    now = datetime.now(timezone.utc).isoformat()
    port = cursor.execute("SELECT * FROM portfolios WHERE strategy_id = ?", (strategy_id,)).fetchone()
    if not port:
        return

    port = dict(port)
    new_balance = port["balance"] + pnl
    new_pnl = port["total_pnl"] + pnl
    new_trades = port["total_trades"] + 1
    new_wins = port["winning_trades"] + (1 if is_win else 0)
    new_losses = port["losing_trades"] + (0 if is_win else 1)
    peak = max(port["peak_balance"], new_balance)
    drawdown = ((peak - new_balance) / peak * 100) if peak > 0 else 0
    max_dd = max(port["max_drawdown_pct"], drawdown)
    initial = port["initial_balance"]
    pnl_pct = ((new_balance - initial) / initial * 100) if initial > 0 else 0

    cursor.execute("""UPDATE portfolios SET balance = ?, total_pnl = ?, total_pnl_pct = ?,
                      total_trades = ?, winning_trades = ?, losing_trades = ?,
                      max_drawdown_pct = ?, peak_balance = ?, updated_at = ?
                      WHERE id = ?""",
                   (round(new_balance, 4), round(new_pnl, 4), round(pnl_pct, 2),
                    new_trades, new_wins, new_losses, round(max_dd, 2), peak,
                    now, port["id"]))


def get_trades(strategy_id: str = None, agent_id: str = None,
               status: str = None, limit: int = 50) -> list:
    """Get trade history."""
    conditions = []
    params = []
    if strategy_id:
        conditions.append("strategy_id = ?")
        params.append(strategy_id)
    if agent_id:
        conditions.append("agent_id = ?")
        params.append(agent_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = " AND ".join(conditions) if conditions else "1=1"
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM trades WHERE {where} ORDER BY opened_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    return [dict(r) for r in rows]


# ── Portfolio ─────────────────────────────────────────────────────────────────

def create_portfolio(user_id: str, strategy_id: str,
                     initial_balance: float = 10000.0,
                     mode: str = "paper") -> dict:
    """Create a portfolio for a user on a strategy."""
    now = datetime.now(timezone.utc).isoformat()
    pid = str(uuid.uuid4())
    with _conn() as c:
        c.execute("""INSERT INTO portfolios
            (id, user_id, strategy_id, initial_balance, balance, peak_balance,
             mode, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, user_id, strategy_id, initial_balance, initial_balance,
             initial_balance, mode, "active", now, now))
    return {"portfolio_id": pid, "balance": initial_balance, "mode": mode}


def get_portfolio(user_id: str = None, strategy_id: str = None,
                  portfolio_id: str = None) -> Optional[dict]:
    with _conn() as c:
        if portfolio_id:
            row = c.execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        elif user_id and strategy_id:
            row = c.execute("SELECT * FROM portfolios WHERE user_id = ? AND strategy_id = ?",
                            (user_id, strategy_id)).fetchone()
        else:
            return None
    if not row:
        return None
    d = dict(row)
    d["active_positions"] = json.loads(d.get("active_positions") or "[]")
    # Compute win rate
    d["win_rate"] = round(d["winning_trades"] / d["total_trades"] * 100, 1) if d["total_trades"] > 0 else 0
    # Compute sharpe (simplified — using total return / max drawdown as proxy)
    d["sharpe_proxy"] = round(d["total_pnl_pct"] / max(d["max_drawdown_pct"], 1), 2)
    return d


def list_portfolios(user_id: str) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM portfolios WHERE user_id = ? ORDER BY created_at DESC",
                         (user_id,)).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["active_positions"] = json.loads(d.get("active_positions") or "[]")
        d["win_rate"] = round(d["winning_trades"] / d["total_trades"] * 100, 1) if d["total_trades"] > 0 else 0
        results.append(d)
    return results


# ── Copy Trading ──────────────────────────────────────────────────────────────

def subscribe_copy(subscriber_id: str, strategy_id: str,
                   sizing_multiplier: float = 1.0,
                   max_position_usd: float = 100.0,
                   auto_execute: bool = False) -> dict:
    """Subscribe to copy trades from a strategy."""
    now = datetime.now(timezone.utc).isoformat()
    sid = str(uuid.uuid4())
    with _conn() as c:
        c.execute("""INSERT INTO copy_subscriptions
            (id, subscriber_id, strategy_id, sizing_multiplier, max_position_usd,
             auto_execute, status, created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (sid, subscriber_id, strategy_id, sizing_multiplier, max_position_usd,
             1 if auto_execute else 0, "active", now))
    return {"subscription_id": sid, "status": "active"}


def get_copy_subscribers(strategy_id: str) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM copy_subscriptions WHERE strategy_id = ? AND status = 'active'",
            (strategy_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Performance Snapshots ─────────────────────────────────────────────────────

def record_snapshot(strategy_id: str, balance: float, pnl: float,
                    pnl_pct: float, open_positions: int = 0):
    """Record a performance snapshot for charting."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""INSERT INTO performance_snapshots
            (strategy_id, balance, pnl, pnl_pct, open_positions, recorded_at)
            VALUES (?,?,?,?,?,?)""",
            (strategy_id, balance, pnl, pnl_pct, open_positions, now))


def get_snapshots(strategy_id: str, limit: int = 100) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT balance, pnl, pnl_pct, open_positions, recorded_at FROM performance_snapshots WHERE strategy_id = ? ORDER BY recorded_at DESC LIMIT ?",
            (strategy_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Leaderboard ───────────────────────────────────────────────────────────────

def trading_leaderboard(limit: int = 20) -> list:
    """Top strategies by P&L %."""
    with _conn() as c:
        rows = c.execute("""
            SELECT p.*, s.name as strategy_name, s.strategy_type, s.pairs
            FROM portfolios p
            JOIN trading_strategies s ON p.strategy_id = s.id
            WHERE p.total_trades >= 5
            ORDER BY p.total_pnl_pct DESC LIMIT ?
        """, (limit,)).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["active_positions"] = json.loads(d.get("active_positions") or "[]")
        d["pairs"] = json.loads(d.get("pairs") or "[]")
        d["win_rate"] = round(d["winning_trades"] / d["total_trades"] * 100, 1) if d["total_trades"] > 0 else 0
        results.append(d)
    return results
