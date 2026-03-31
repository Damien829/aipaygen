"""Trading engine — strategy management, paper trading, P&L tracking."""
import sqlite3
import json
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import ta_indicators
import exchange_connectors

_log = logging.getLogger(__name__)

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


# ── Auto-Execution Engine ────────────────────────────────────────────────────

def check_risk_limits(strategy_id: str) -> dict:
    """Check if a strategy has hit its daily loss limit, stop-loss, or take-profit.

    Returns {allowed: bool, reason: str}.
    """
    strategy = get_strategy(strategy_id)
    if not strategy:
        return {"allowed": False, "reason": "strategy not found"}

    daily_loss_limit = strategy.get("daily_loss_limit", 50.0)
    stop_loss_pct = strategy.get("stop_loss_pct", 5.0)
    take_profit_pct = strategy.get("take_profit_pct", 10.0)

    # Check daily realized P&L
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(pnl), 0) as daily_pnl FROM trades "
            "WHERE strategy_id = ? AND status = 'closed' AND closed_at >= ?",
            (strategy_id, today_start)
        ).fetchone()
    daily_pnl = row["daily_pnl"] if row else 0.0

    if daily_pnl <= -daily_loss_limit:
        return {"allowed": False, "reason": f"daily loss limit hit ({daily_pnl:.2f} <= -{daily_loss_limit})"}

    # Check portfolio-level stop-loss and take-profit
    with _conn() as c:
        port = c.execute(
            "SELECT * FROM portfolios WHERE strategy_id = ?", (strategy_id,)
        ).fetchone()

    if port:
        port = dict(port)
        initial = port["initial_balance"]
        balance = port["balance"]
        if initial > 0:
            pnl_pct = ((balance - initial) / initial) * 100
            if pnl_pct <= -stop_loss_pct:
                return {"allowed": False, "reason": f"portfolio stop-loss hit ({pnl_pct:.2f}% <= -{stop_loss_pct}%)"}
            if pnl_pct >= take_profit_pct:
                return {"allowed": False, "reason": f"portfolio take-profit hit ({pnl_pct:.2f}% >= {take_profit_pct}%)"}

    return {"allowed": True, "reason": "within risk limits"}


def auto_execute_strategy(strategy_id: str) -> dict:
    """Auto-execute an active strategy: fetch prices, generate signals, manage trades.

    Returns summary of actions taken.
    """
    strategy = get_strategy(strategy_id)
    if not strategy:
        return {"error": "strategy not found"}
    if strategy["status"] != "active":
        return {"error": f"strategy status is '{strategy['status']}', not 'active'"}

    pairs = strategy.get("pairs", [])
    config = strategy.get("config", {})
    strategy_type = strategy.get("strategy_type", "custom")
    agent_id = strategy["agent_id"]
    exchange = strategy.get("exchange", "paper")
    max_position_usd = strategy.get("max_position_usd", 100.0)
    stop_loss_pct = strategy.get("stop_loss_pct", 5.0)
    take_profit_pct = strategy.get("take_profit_pct", 10.0)

    actions = []

    # Check risk limits before proceeding
    risk = check_risk_limits(strategy_id)
    if not risk["allowed"]:
        # Even if blocked, still enforce stop-loss / take-profit on open positions
        _enforce_exit_limits(strategy_id, agent_id, stop_loss_pct, take_profit_pct, actions)
        actions.append({"action": "risk_blocked", "reason": risk["reason"]})
        _record_strategy_snapshot(strategy_id)
        return {"strategy_id": strategy_id, "status": "risk_blocked",
                "reason": risk["reason"], "actions": actions}

    # Process each pair
    for pair in pairs:
        try:
            # Get current price
            price_data = exchange_connectors.get_price(pair, exchange)
            if not price_data:
                actions.append({"pair": pair, "action": "skip", "reason": "no price available"})
                continue
            current_price = price_data["price"]

            # Get historical prices for signal generation
            hist = exchange_connectors.get_historical_prices(pair, days=60)
            if len(hist) < 2:
                actions.append({"pair": pair, "action": "skip", "reason": "insufficient historical data"})
                continue
            hist_prices = [h["price"] for h in hist]
            # Append current price to the end for the latest signal
            hist_prices.append(current_price)

            # Generate signals
            signals = ta_indicators.generate_signals(hist_prices, strategy_type, config)
            if not signals:
                actions.append({"pair": pair, "action": "skip", "reason": "no signals generated"})
                continue

            latest_signal = signals[-1]

            # Check if there's already an open position on this pair
            open_trades = get_trades(strategy_id=strategy_id, status="open")
            open_for_pair = [t for t in open_trades if t["pair"] == pair]

            if latest_signal["signal"] == "buy" and not open_for_pair:
                # Open a long position
                quantity = max_position_usd / current_price if current_price > 0 else 0
                if quantity > 0:
                    trade = open_trade(
                        strategy_id=strategy_id, agent_id=agent_id,
                        pair=pair, side="long", entry_price=current_price,
                        quantity=round(quantity, 8), exchange=exchange,
                        entry_reason=latest_signal.get("reason", "buy signal")
                    )
                    actions.append({"pair": pair, "action": "open_long",
                                    "price": current_price, "quantity": round(quantity, 8),
                                    "trade_id": trade["trade_id"],
                                    "reason": latest_signal.get("reason", "")})
                    # Execute copy trades
                    execute_copy_trades(strategy_id, trade)

            elif latest_signal["signal"] == "sell" and open_for_pair:
                # Close open positions
                for t in open_for_pair:
                    result = close_trade(t["id"], current_price,
                                         exit_reason=latest_signal.get("reason", "sell signal"))
                    actions.append({"pair": pair, "action": "close",
                                    "price": current_price, "pnl": result.get("pnl", 0),
                                    "trade_id": t["id"],
                                    "reason": latest_signal.get("reason", "")})
                    execute_copy_trades(strategy_id, {"trade_id": t["id"],
                                                       "action": "close", "exit_price": current_price})

            else:
                actions.append({"pair": pair, "action": "hold",
                                "signal": latest_signal["signal"],
                                "reason": latest_signal.get("reason", "")})

        except Exception as e:
            _log.error(f"auto_execute error for {pair} on strategy {strategy_id}: {e}")
            actions.append({"pair": pair, "action": "error", "reason": str(e)})

    # Enforce stop-loss / take-profit on all open positions
    _enforce_exit_limits(strategy_id, agent_id, stop_loss_pct, take_profit_pct, actions)

    # Record performance snapshot
    _record_strategy_snapshot(strategy_id)

    return {"strategy_id": strategy_id, "status": "executed", "actions": actions}


def _enforce_exit_limits(strategy_id: str, agent_id: str,
                         stop_loss_pct: float, take_profit_pct: float,
                         actions: list):
    """Close any open positions that have hit stop-loss or take-profit."""
    open_trades = get_trades(strategy_id=strategy_id, status="open")
    for t in open_trades:
        try:
            price_data = exchange_connectors.get_price(t["pair"])
            if not price_data:
                continue
            current_price = price_data["price"]
            entry = t["entry_price"]
            side = t["side"]

            if side == "long":
                pnl_pct = ((current_price - entry) / entry) * 100
            else:
                pnl_pct = ((entry - current_price) / entry) * 100

            if pnl_pct <= -stop_loss_pct:
                result = close_trade(t["id"], current_price,
                                      exit_reason=f"stop-loss triggered ({pnl_pct:.2f}%)")
                actions.append({"pair": t["pair"], "action": "stop_loss",
                                "price": current_price, "pnl": result.get("pnl", 0),
                                "pnl_pct": round(pnl_pct, 2), "trade_id": t["id"]})
                execute_copy_trades(strategy_id, {"trade_id": t["id"],
                                                   "action": "close", "exit_price": current_price})

            elif pnl_pct >= take_profit_pct:
                result = close_trade(t["id"], current_price,
                                      exit_reason=f"take-profit triggered ({pnl_pct:.2f}%)")
                actions.append({"pair": t["pair"], "action": "take_profit",
                                "price": current_price, "pnl": result.get("pnl", 0),
                                "pnl_pct": round(pnl_pct, 2), "trade_id": t["id"]})
                execute_copy_trades(strategy_id, {"trade_id": t["id"],
                                                   "action": "close", "exit_price": current_price})

        except Exception as e:
            _log.error(f"exit limit check error for trade {t['id']}: {e}")


def _record_strategy_snapshot(strategy_id: str):
    """Record a performance snapshot for the strategy."""
    with _conn() as c:
        port = c.execute(
            "SELECT * FROM portfolios WHERE strategy_id = ?", (strategy_id,)
        ).fetchone()
        open_count = c.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE strategy_id = ? AND status = 'open'",
            (strategy_id,)
        ).fetchone()["cnt"]
    if port:
        port = dict(port)
        record_snapshot(strategy_id, port["balance"], port["total_pnl"],
                        port["total_pnl_pct"], open_count)


def execute_copy_trades(strategy_id: str, trade: dict):
    """Execute proportionally scaled trades for all copy subscribers of a strategy.

    Args:
        strategy_id: The source strategy being copied.
        trade: Dict with trade details — either a newly opened trade
               (with trade_id, pair, side, entry_price, quantity) or a close
               action (with trade_id, action='close', exit_price).
    """
    subscribers = get_copy_subscribers(strategy_id)
    if not subscribers:
        return

    for sub in subscribers:
        if not sub.get("auto_execute"):
            continue

        subscriber_id = sub["subscriber_id"]
        multiplier = sub.get("sizing_multiplier", 1.0)
        max_pos = sub.get("max_position_usd", 100.0)

        try:
            if trade.get("action") == "close":
                # Close the corresponding copy trade
                source_trade_id = trade.get("trade_id")
                exit_price = trade.get("exit_price", 0)
                with _conn() as c:
                    copy_trade = c.execute(
                        "SELECT id FROM trades WHERE agent_id = ? AND entry_reason LIKE ? AND status = 'open'",
                        (subscriber_id, f"%copy:{source_trade_id}%")
                    ).fetchone()
                if copy_trade:
                    close_trade(copy_trade["id"], exit_price,
                                exit_reason=f"copy close from {strategy_id}")
            else:
                # Open a proportionally scaled copy trade
                pair = trade.get("pair", "")
                side = trade.get("side", "long")
                entry_price = trade.get("entry_price", 0)
                quantity = trade.get("quantity", 0) * multiplier

                # Cap to subscriber's max position
                if entry_price > 0:
                    max_qty = max_pos / entry_price
                    quantity = min(quantity, max_qty)

                if quantity > 0 and entry_price > 0:
                    open_trade(
                        strategy_id=strategy_id, agent_id=subscriber_id,
                        pair=pair, side=side, entry_price=entry_price,
                        quantity=round(quantity, 8), exchange="paper",
                        entry_reason=f"copy:{trade.get('trade_id', '')} from {strategy_id}"
                    )
        except Exception as e:
            _log.error(f"copy trade error for subscriber {subscriber_id}: {e}")


def run_all_active_strategies() -> dict:
    """Find all strategies with status='active' and auto-execute each.

    Returns summary with results per strategy.
    """
    strategies = list_strategies(status="active")
    results = []
    total_actions = 0

    for s in strategies:
        try:
            result = auto_execute_strategy(s["id"])
            action_count = len(result.get("actions", []))
            total_actions += action_count
            results.append({
                "strategy_id": s["id"],
                "name": s["name"],
                "status": result.get("status", "unknown"),
                "action_count": action_count,
                "actions": result.get("actions", []),
            })
        except Exception as e:
            _log.error(f"run_all error for strategy {s['id']}: {e}")
            results.append({
                "strategy_id": s["id"],
                "name": s["name"],
                "status": "error",
                "error": str(e),
            })

    return {
        "strategies_processed": len(results),
        "total_actions": total_actions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
