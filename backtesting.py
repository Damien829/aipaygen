"""Backtesting engine — simulate trading strategies against historical data."""
import json
import uuid
import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional

import ta_indicators
import exchange_connectors

DB_PATH = os.path.join(os.path.dirname(__file__), "trading.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


def init_backtest_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS backtest_results (
            id TEXT PRIMARY KEY,
            strategy_type TEXT NOT NULL,
            config TEXT NOT NULL DEFAULT '{}',
            pair TEXT NOT NULL,
            days INTEGER NOT NULL DEFAULT 30,
            initial_balance REAL NOT NULL DEFAULT 10000.0,
            final_balance REAL NOT NULL DEFAULT 10000.0,
            total_pnl REAL DEFAULT 0.0,
            total_pnl_pct REAL DEFAULT 0.0,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0.0,
            max_drawdown_pct REAL DEFAULT 0.0,
            sharpe_ratio REAL DEFAULT 0.0,
            avg_trade_pnl REAL DEFAULT 0.0,
            best_trade_pnl REAL DEFAULT 0.0,
            worst_trade_pnl REAL DEFAULT 0.0,
            avg_hold_periods INTEGER DEFAULT 0,
            trades_json TEXT DEFAULT '[]',
            equity_curve TEXT DEFAULT '[]',
            signals_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            duration_ms INTEGER DEFAULT 0
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bt_type ON backtest_results(strategy_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bt_pair ON backtest_results(pair)")


def run_backtest(strategy_type: str, config: dict, pair: str,
                 days: int = 30, initial_balance: float = 10000.0,
                 position_size_pct: float = 10.0,
                 stop_loss_pct: float = 5.0,
                 take_profit_pct: float = 10.0) -> dict:
    """Run a full backtest simulation.

    Returns detailed results with trades, equity curve, and performance metrics.
    """
    import time
    t0 = time.time()

    # Fetch historical data
    historical = exchange_connectors.get_historical_prices(pair, days=days)
    if len(historical) < 10:
        return {"error": f"Insufficient data for {pair} ({len(historical)} points, need 10+)"}

    prices = [h["price"] for h in historical]
    timestamps = [h["timestamp"] for h in historical]

    # Generate signals
    signals = ta_indicators.generate_signals(prices, strategy_type, config)

    # Simulate trades
    balance = initial_balance
    position = None  # {side, entry_price, quantity, entry_idx}
    trades = []
    equity_curve = []
    peak_balance = initial_balance
    max_drawdown = 0.0
    daily_returns = []

    for i in range(len(prices)):
        price = prices[i]
        signal = signals[i]

        # Check stop loss / take profit on open position
        if position:
            if position["side"] == "long":
                unrealized_pnl_pct = ((price - position["entry_price"]) / position["entry_price"]) * 100
            else:
                unrealized_pnl_pct = ((position["entry_price"] - price) / position["entry_price"]) * 100

            # Stop loss
            if unrealized_pnl_pct <= -stop_loss_pct:
                pnl = position["quantity"] * (price - position["entry_price"])
                if position["side"] == "short":
                    pnl = position["quantity"] * (position["entry_price"] - price)
                balance += pnl
                trades.append({
                    "entry_idx": position["entry_idx"],
                    "exit_idx": i,
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": price,
                    "quantity": position["quantity"],
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(unrealized_pnl_pct, 2),
                    "hold_periods": i - position["entry_idx"],
                    "exit_reason": "stop_loss",
                    "entry_time": timestamps[position["entry_idx"]],
                    "exit_time": timestamps[i],
                })
                position = None

            # Take profit
            elif unrealized_pnl_pct >= take_profit_pct:
                pnl = position["quantity"] * (price - position["entry_price"])
                if position["side"] == "short":
                    pnl = position["quantity"] * (position["entry_price"] - price)
                balance += pnl
                trades.append({
                    "entry_idx": position["entry_idx"],
                    "exit_idx": i,
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": price,
                    "quantity": position["quantity"],
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(unrealized_pnl_pct, 2),
                    "hold_periods": i - position["entry_idx"],
                    "exit_reason": "take_profit",
                    "entry_time": timestamps[position["entry_idx"]],
                    "exit_time": timestamps[i],
                })
                position = None

        # Process signal
        if signal["signal"] == "buy" and position is None:
            alloc = balance * (position_size_pct / 100)
            qty = alloc / price
            position = {
                "side": "long",
                "entry_price": price,
                "quantity": qty,
                "entry_idx": i,
            }
        elif signal["signal"] == "sell" and position is not None:
            if position["side"] == "long":
                pnl = position["quantity"] * (price - position["entry_price"])
                pnl_pct = ((price - position["entry_price"]) / position["entry_price"]) * 100
            else:
                pnl = position["quantity"] * (position["entry_price"] - price)
                pnl_pct = ((position["entry_price"] - price) / position["entry_price"]) * 100
            balance += pnl
            trades.append({
                "entry_idx": position["entry_idx"],
                "exit_idx": i,
                "side": position["side"],
                "entry_price": position["entry_price"],
                "exit_price": price,
                "quantity": position["quantity"],
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "hold_periods": i - position["entry_idx"],
                "exit_reason": "signal",
                "entry_time": timestamps[position["entry_idx"]],
                "exit_time": timestamps[i],
            })
            position = None

        # Track equity
        current_equity = balance
        if position:
            if position["side"] == "long":
                current_equity += position["quantity"] * (price - position["entry_price"])
            else:
                current_equity += position["quantity"] * (position["entry_price"] - price)

        equity_curve.append({"idx": i, "balance": round(current_equity, 2),
                             "timestamp": timestamps[i], "price": price})

        peak_balance = max(peak_balance, current_equity)
        drawdown = ((peak_balance - current_equity) / peak_balance * 100) if peak_balance > 0 else 0
        max_drawdown = max(max_drawdown, drawdown)

        if i > 0:
            prev_equity = equity_curve[-2]["balance"] if len(equity_curve) > 1 else initial_balance
            daily_ret = (current_equity - prev_equity) / prev_equity if prev_equity > 0 else 0
            daily_returns.append(daily_ret)

    # Close any open position at end
    if position:
        price = prices[-1]
        if position["side"] == "long":
            pnl = position["quantity"] * (price - position["entry_price"])
            pnl_pct = ((price - position["entry_price"]) / position["entry_price"]) * 100
        else:
            pnl = position["quantity"] * (position["entry_price"] - price)
            pnl_pct = ((position["entry_price"] - price) / position["entry_price"]) * 100
        balance += pnl
        trades.append({
            "entry_idx": position["entry_idx"],
            "exit_idx": len(prices) - 1,
            "side": position["side"],
            "entry_price": position["entry_price"],
            "exit_price": price,
            "quantity": position["quantity"],
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "hold_periods": len(prices) - 1 - position["entry_idx"],
            "exit_reason": "end_of_data",
            "entry_time": timestamps[position["entry_idx"]],
            "exit_time": timestamps[-1],
        })

    # Calculate metrics
    winning = [t for t in trades if t["pnl"] > 0]
    losing = [t for t in trades if t["pnl"] <= 0]
    total_pnl = balance - initial_balance
    total_pnl_pct = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0
    win_rate = (len(winning) / len(trades) * 100) if trades else 0
    avg_pnl = (sum(t["pnl"] for t in trades) / len(trades)) if trades else 0
    best_pnl = max((t["pnl"] for t in trades), default=0)
    worst_pnl = min((t["pnl"] for t in trades), default=0)
    avg_hold = (sum(t["hold_periods"] for t in trades) / len(trades)) if trades else 0

    # Sharpe ratio (annualized, assuming daily data)
    if daily_returns and len(daily_returns) > 1:
        mean_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_ret = variance ** 0.5
        sharpe = (mean_ret / std_ret * (365 ** 0.5)) if std_ret > 0 else 0
    else:
        sharpe = 0

    duration_ms = int((time.time() - t0) * 1000)

    result = {
        "id": str(uuid.uuid4()),
        "strategy_type": strategy_type,
        "config": config,
        "pair": pair,
        "days": days,
        "data_points": len(prices),
        "initial_balance": initial_balance,
        "final_balance": round(balance, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "total_trades": len(trades),
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 2),
        "avg_trade_pnl": round(avg_pnl, 2),
        "best_trade_pnl": round(best_pnl, 2),
        "worst_trade_pnl": round(worst_pnl, 2),
        "avg_hold_periods": round(avg_hold, 1),
        "position_size_pct": position_size_pct,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "trades": trades,
        "equity_curve": equity_curve,
        "signals_summary": {
            "buy": sum(1 for s in signals if s["signal"] == "buy"),
            "sell": sum(1 for s in signals if s["signal"] == "sell"),
            "hold": sum(1 for s in signals if s["signal"] == "hold"),
        },
        "duration_ms": duration_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Save to DB
    _save_result(result)
    return result


def _save_result(r: dict):
    try:
        with _conn() as c:
            c.execute("""INSERT INTO backtest_results
                (id, strategy_type, config, pair, days, initial_balance, final_balance,
                 total_pnl, total_pnl_pct, total_trades, winning_trades, losing_trades,
                 win_rate, max_drawdown_pct, sharpe_ratio, avg_trade_pnl, best_trade_pnl,
                 worst_trade_pnl, avg_hold_periods, trades_json, equity_curve, signals_json,
                 created_at, duration_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], r["strategy_type"], json.dumps(r["config"]), r["pair"], r["days"],
                 r["initial_balance"], r["final_balance"], r["total_pnl"], r["total_pnl_pct"],
                 r["total_trades"], r["winning_trades"], r["losing_trades"], r["win_rate"],
                 r["max_drawdown_pct"], r["sharpe_ratio"], r["avg_trade_pnl"],
                 r["best_trade_pnl"], r["worst_trade_pnl"], r["avg_hold_periods"],
                 json.dumps(r["trades"]), json.dumps(r["equity_curve"]),
                 json.dumps(r.get("signals_summary", {})), r["created_at"], r["duration_ms"]))
    except Exception:
        pass


def get_backtest(backtest_id: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM backtest_results WHERE id = ?", (backtest_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d.get("config") or "{}")
    d["trades_json"] = json.loads(d.get("trades_json") or "[]")
    d["equity_curve"] = json.loads(d.get("equity_curve") or "[]")
    d["signals_json"] = json.loads(d.get("signals_json") or "{}")
    return d


def list_backtests(strategy_type: str = None, pair: str = None, limit: int = 20) -> list:
    conditions, params = [], []
    if strategy_type:
        conditions.append("strategy_type = ?")
        params.append(strategy_type)
    if pair:
        conditions.append("pair = ?")
        params.append(pair)
    where = " AND ".join(conditions) if conditions else "1=1"
    with _conn() as c:
        rows = c.execute(
            f"SELECT id, strategy_type, pair, days, total_pnl_pct, win_rate, sharpe_ratio, total_trades, max_drawdown_pct, created_at, duration_ms FROM backtest_results WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    return [dict(r) for r in rows]
