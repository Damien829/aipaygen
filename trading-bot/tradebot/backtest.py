"""Long-only, one-position backtest engine with fees and slippage.

Rule: target[i] is decided on candle i's close; any change fills at candle i+1's open, adjusted by
slippage against us, minus a fee on the traded value. The final open position is closed at the last close."""
import math
from dataclasses import dataclass, field


@dataclass
class Trade:
    entry_t: int
    entry_price: float
    exit_t: int = 0
    exit_price: float = 0.0
    qty: float = 0.0
    pnl: float = 0.0
    ret: float = 0.0
    fees: float = 0.0


@dataclass
class Result:
    trades: list = field(default_factory=list)
    equity: list = field(default_factory=list)   # per candle: (t, equity)
    metrics: dict = field(default_factory=dict)


def run(candles, targets, capital=10_000.0, fee=0.006, slippage_bps=5.0, bars_per_year=8760):
    if len(candles) != len(targets):
        raise ValueError("targets must match candles")
    if len(candles) < 3:
        raise ValueError("need at least 3 candles")
    slip = slippage_bps / 10_000
    cash, qty, open_trade = capital, 0.0, None
    trades, equity, fees_total = [], [], 0.0

    def buy(i):
        nonlocal cash, qty, open_trade, fees_total
        px = candles[i]["o"] * (1 + slip)
        q = cash / (px * (1 + fee))
        f = q * px * fee
        cash -= q * px + f
        qty, fees_total = q, fees_total + f
        open_trade = Trade(candles[i]["t"], px, qty=q, fees=f)

    def sell(i, px_raw):
        nonlocal cash, qty, open_trade, fees_total
        px = px_raw * (1 - slip)
        f = qty * px * fee
        cash += qty * px - f
        fees_total += f
        t = open_trade
        t.exit_t, t.exit_price, t.fees = candles[i]["t"], px, t.fees + f
        cost = t.qty * t.entry_price
        t.pnl = t.qty * px - f - cost - (t.fees - f)
        t.ret = t.pnl / (cost + (t.fees - f))
        trades.append(t)
        qty, open_trade = 0.0, None

    for i, c in enumerate(candles):
        if i > 0:  # act on the previous close's target at this open
            want = targets[i - 1]
            if want and qty == 0:
                buy(i)
            elif not want and qty > 0:
                sell(i, c["o"])
        equity.append((c["t"], cash + qty * c["c"]))
    if qty > 0:
        sell(len(candles) - 1, candles[-1]["c"])
        equity[-1] = (equity[-1][0], cash)

    return Result(trades, equity, _metrics(candles, trades, equity, capital, fees_total, bars_per_year))


def _metrics(candles, trades, equity, capital, fees_total, bpy):
    eq = [e for _, e in equity]
    rets = [b / a - 1 for a, b in zip(eq, eq[1:]) if a > 0]
    mean = sum(rets) / len(rets) if rets else 0.0
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
    peak, mdd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak)
    wins = [t for t in trades if t.pnl > 0]
    return {
        "start_capital": capital,
        "end_equity": eq[-1],
        "total_return_pct": (eq[-1] / capital - 1) * 100,
        "buy_hold_return_pct": (candles[-1]["c"] / candles[0]["o"] - 1) * 100,
        "max_drawdown_pct": mdd * 100,
        "sharpe": (mean / sd * math.sqrt(bpy)) if sd > 0 else 0.0,
        "trades": len(trades),
        "win_rate_pct": (len(wins) / len(trades) * 100) if trades else 0.0,
        "fees_paid": fees_total,
        "bars": len(candles),
    }
