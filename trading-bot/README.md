# tradebot

A crypto trading bot built in stages. **Stage 1 (this): the backtester.** Paper trading, alerts, and
live automation come next, each only after the previous one is working and tested.

> Historical simulation only. Past results do not predict future results. Backtests can be overfit,
> suffer look-ahead bias, and understate real fees and slippage. **Not financial advice.**

## Setup
```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
No API key is needed for stage 1: candles come from Coinbase's public market-data API.

## Use
```
python -m tradebot fetch --product BTC-USD --granularity 1h --days 90   # saves data/BTC-USD_1h.csv
python -m tradebot backtest --strategy ma_cross --param fast=20 --param slow=50
python -m tradebot backtest --strategy rsi_reversion --param low=30 --param high=55
python -m tradebot backtest --synthetic        # random-walk demo data, NOT real prices
python -m pytest                               # tests
```
Output: return vs buy & hold, max drawdown, Sharpe, trade count, win rate, fees, plus
`results/<tag>_trades.csv` (trade log) and `results/<tag>.png` (price + equity chart).

## How the simulation works
- Long-only, one position at a time. A signal on candle *i*'s close fills at candle *i+1*'s open (no look-ahead; tested).
- Costs: per-side fee (default 0.6%, Coinbase's retail-tier taker fee; set `--fee`) and slippage (default 5 bps).
- An open position at the end is closed at the last close.
- Strategies are plug-ins in `tradebot/strategy.py` (`@register("name")`, `positions(candles)`).
  `ma_cross` and `rsi_reversion` are **examples** to exercise the engine, not recommendations.

## Rules for the later stages (from the brief)
- No real-money order, and live trading stays OFF, until you say "go live" after seeing paper results.
- You create the exchange API key yourself: trade-only, **no withdrawal permission**, stored in a secret
  store (macOS Keychain service `trading-bot`). It is never printed, logged or committed.
- Live stage will have hard limits (max position, max daily loss, max open positions, orders per hour),
  a kill switch, auto-halt on loss limit or repeated errors, idempotent orders, and a real-position check on start.
