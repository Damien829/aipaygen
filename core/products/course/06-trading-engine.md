# Lesson 06: Trading Engine

## What You Will Build

A complete trading engine: strategy templates (momentum, mean reversion, sentiment, DCA), paper trading with portfolio tracking, a backtesting simulator, risk management with stop-loss and daily limits, copy trading, and a performance leaderboard. This is the most complex module in the entire platform.

## Strategy Templates

The trading engine comes with pre-built strategy templates. Each template defines default configuration and pairs. Users can use them as-is or customize the parameters:

```python
STRATEGY_TEMPLATES = {
    "momentum": {
        "name": "Momentum",
        "description": "Buy when price crosses above MA, sell when below",
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
    "dca": {
        "name": "Dollar Cost Average",
        "description": "Buy fixed amounts at regular intervals",
        "config": {
            "interval_hours": 24,
            "amount_usd": 10.0,
            "max_total_usd": 1000.0,
        },
        "default_pairs": ["BTC/USD", "ETH/USD"],
    },
}
```

## Creating a Strategy

Strategies belong to agents and start in "paused" state. They include built-in risk parameters: maximum position size, stop-loss percentage, take-profit target, and daily loss limit:

```python
def create_strategy(agent_id: str, name: str, strategy_type: str = "custom",
                    config: dict = None, pairs: list = None,
                    exchange: str = "paper", mode: str = "paper",
                    max_position_usd: float = 100.0,
                    stop_loss_pct: float = 5.0,
                    take_profit_pct: float = 10.0,
                    daily_loss_limit: float = 50.0) -> dict:
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
            (id, agent_id, name, strategy_type, config, pairs, exchange,
             mode, status, max_position_usd, stop_loss_pct, take_profit_pct,
             daily_loss_limit, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, agent_id, name, strategy_type,
             json.dumps(config or {}), json.dumps(pairs or []),
             exchange, mode, "paused", max_position_usd, stop_loss_pct,
             take_profit_pct, daily_loss_limit, now, now))

    return {"strategy_id": sid, "name": name, "status": "paused", "mode": mode}
```

Everything starts in paper mode. Users graduate to live trading only when they have confidence in their strategy.

## Trade Execution and P&L

Opening a trade records the entry. Closing it calculates P&L atomically, including long/short direction:

```python
def close_trade(trade_id: str, exit_price: float, exit_reason: str = "") -> dict:
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
        else:  # short
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

        # Update portfolio stats
        _update_portfolio_from_trade(c, trade["strategy_id"], pnl, pnl > 0)

    return {"trade_id": trade_id, "pnl": round(pnl, 4), "pnl_pct": round(pnl_pct, 2)}
```

The portfolio update happens in the same transaction. Win rate, drawdown, and peak balance are all tracked:

```python
def _update_portfolio_from_trade(cursor, strategy_id, pnl, is_win):
    port = cursor.execute(
        "SELECT * FROM portfolios WHERE strategy_id = ?", (strategy_id,)
    ).fetchone()
    if not port:
        return
    port = dict(port)
    
    new_balance = port["balance"] + pnl
    peak = max(port["peak_balance"], new_balance)
    drawdown = ((peak - new_balance) / peak * 100) if peak > 0 else 0
    
    cursor.execute("""UPDATE portfolios SET balance = ?, total_pnl = total_pnl + ?,
                      total_trades = total_trades + 1,
                      winning_trades = winning_trades + ?,
                      losing_trades = losing_trades + ?,
                      max_drawdown_pct = ?, peak_balance = ?
                      WHERE id = ?""",
                   (new_balance, pnl, 1 if is_win else 0,
                    0 if is_win else 1, max(port["max_drawdown_pct"], drawdown),
                    peak, port["id"]))
```

## The Backtesting Engine

Before risking real money, backtest strategies against historical data. The backtester simulates trade execution including stop-loss and take-profit triggers:

```python
def run_backtest(strategy_type: str, config: dict, pair: str,
                 days: int = 30, initial_balance: float = 10000.0,
                 position_size_pct: float = 10.0,
                 stop_loss_pct: float = 5.0,
                 take_profit_pct: float = 10.0) -> dict:
    # Fetch historical prices
    historical = exchange_connectors.get_historical_prices(pair, days=days)
    prices = [h["price"] for h in historical]

    # Generate signals using technical indicators
    signals = ta_indicators.generate_signals(prices, strategy_type, config)

    balance = initial_balance
    position = None
    trades = []
    equity_curve = []

    for i in range(len(prices)):
        price = prices[i]
        signal = signals[i]

        # Check stop-loss / take-profit on open position
        if position:
            unrealized_pnl_pct = ((price - position["entry_price"])
                                   / position["entry_price"]) * 100
            if unrealized_pnl_pct <= -stop_loss_pct:
                # Stop-loss triggered — close position
                pnl = position["quantity"] * (price - position["entry_price"])
                balance += pnl
                trades.append({"exit_reason": "stop_loss", "pnl": pnl, ...})
                position = None

        # Process signal: buy or sell
        if signal["signal"] == "buy" and position is None:
            alloc = balance * (position_size_pct / 100)
            qty = alloc / price
            position = {"entry_price": price, "quantity": qty, "side": "long"}
        elif signal["signal"] == "sell" and position is not None:
            pnl = position["quantity"] * (price - position["entry_price"])
            balance += pnl
            trades.append({"exit_reason": "signal", "pnl": pnl, ...})
            position = None

        equity_curve.append({"balance": balance, "price": price})

    # Calculate Sharpe ratio from daily returns
    sharpe = calculate_sharpe(equity_curve)

    return {
        "initial_balance": initial_balance,
        "final_balance": round(balance, 2),
        "total_trades": len(trades),
        "win_rate": round(len([t for t in trades if t["pnl"] > 0]) / max(len(trades), 1) * 100, 1),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 2),
        "trades": trades,
        "equity_curve": equity_curve,
    }
```

The backtest returns everything you need to evaluate a strategy: win rate, drawdown, Sharpe ratio, individual trades, and the equity curve for charting.

## Risk Management

Before every auto-execution cycle, the engine checks risk limits. If the daily loss limit or portfolio stop-loss is hit, no new trades are opened:

```python
def check_risk_limits(strategy_id: str) -> dict:
    strategy = get_strategy(strategy_id)
    daily_loss_limit = strategy.get("daily_loss_limit", 50.0)

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0
    ).isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(pnl), 0) as daily_pnl FROM trades "
            "WHERE strategy_id = ? AND status = 'closed' AND closed_at >= ?",
            (strategy_id, today_start)
        ).fetchone()
    daily_pnl = row["daily_pnl"]

    if daily_pnl <= -daily_loss_limit:
        return {"allowed": False,
                "reason": f"daily loss limit hit ({daily_pnl:.2f})"}
    return {"allowed": True, "reason": "within risk limits"}
```

## Copy Trading

Users can subscribe to copy trades from profitable strategies. Positions are scaled by a multiplier and capped at a maximum:

```python
def execute_copy_trades(strategy_id: str, trade: dict):
    subscribers = get_copy_subscribers(strategy_id)
    for sub in subscribers:
        if not sub.get("auto_execute"):
            continue
        multiplier = sub.get("sizing_multiplier", 1.0)
        max_pos = sub.get("max_position_usd", 100.0)
        
        quantity = trade.get("quantity", 0) * multiplier
        entry_price = trade.get("entry_price", 0)
        if entry_price > 0:
            max_qty = max_pos / entry_price
            quantity = min(quantity, max_qty)
        
        if quantity > 0:
            open_trade(
                strategy_id=strategy_id,
                agent_id=sub["subscriber_id"],
                pair=trade["pair"],
                side=trade["side"],
                entry_price=entry_price,
                quantity=round(quantity, 8),
                entry_reason=f"copy:{trade['trade_id']}"
            )
```

## Exercise

1. Create the trading database tables (strategies, trades, portfolios).
2. Implement `create_strategy` using the momentum template.
3. Build `open_trade` and `close_trade` with P&L calculation.
4. Implement `run_backtest` against sample historical price data.
5. Add `check_risk_limits` and verify it blocks trades after the daily loss limit.

Next lesson: building webhook infrastructure for event-driven architecture.
