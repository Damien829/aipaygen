# Handoff: trade bot -> Windows PC

Paste the "Start prompt" at the bottom into a new Claude Code session opened in the `trading-bot` folder on the PC.

## Where things stand
- **Stage 1 (backtester): done, 9 tests pass.** Code: `tradebot/` (data, strategy, backtest, report, cli), tests in `tests/`.
- Built in a cloud sandbox that blocks Coinbase, so it has **never run on real prices**. Tested on random-walk demo data and a mocked fetch only. First job on the PC: fetch real candles and confirm the whole path works.
- Decisions made by Damien: **crypto on Coinbase Advanced Trade**; **start with the backtester**, no strategy chosen yet (`ma_cross`, `rsi_reversion` are examples only).
- Code is on branch `claude/sweet-ramanujan-hvf75l` of `damien829/aipaygen`, folder `trading-bot/`. It is meant to be its own project: copy the folder out to its own repo/folder (e.g. `C:\Users\<you>\trading-bot`) and `git init` there.
- Known nit: the stage-1 commit message links the wrong session. Harmless.

## Get it running on Windows (PowerShell)
```
git clone https://github.com/damien829/aipaygen.git
cd aipaygen
git checkout claude/sweet-ramanujan-hvf75l
Copy-Item -Recurse trading-bot C:\trading-bot
cd C:\trading-bot
py -3 -m venv .venv
.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
python -m pytest                 # expect 9 passed
python -m tradebot fetch --product BTC-USD --granularity 1h --days 90
python -m tradebot backtest --strategy ma_cross
```
Needs Python 3.10+ (built on 3.13). Windows notes: use `py -3`, backslash paths, and `Activate.ps1` instead of `source`. Pure-Python core, only matplotlib as a dependency, so nothing needs compiling.

## Next stages (build in order, each tested before the next)
2. **Paper trading**: live Coinbase prices, simulated fills, same strategy code, running P&L, phone-friendly dashboard.
3. **Alerts**: push to phone via ntfy on signals, fills, errors, limit hits.
4. **Live automation**: built but OFF by default behind an explicit config flag. Hard limits (max position size, max daily loss, max open positions, max orders per hour), kill switch, auto-halt on loss limit or repeated errors, idempotent orders, check against exchange's real positions on start, full logs.

## Hard rules
- Never place a real-money order or turn live trading on. Needs Damien's own "go live", in his words, after he has seen paper results.
- API keys are Damien's: he creates them **trade-only, no withdrawal permission**. On Windows store them in **Windows Credential Manager** (use the `keyring` package, service name `trading-bot`), not on macOS Keychain as the original brief said. Never print, log or commit keys; `.env` is already gitignored.
- No financial advice. Present backtests as historical simulation with limits (overfitting, look-ahead bias, fees).
- Python with pinned dependencies; README must cover setup, keys, each stage and the kill switch.
- Report to Damien in short, plain words after each stage.

## Later idea (not now)
A strategy with a real track record could sell its signals per call over x402 on AIPayGen's 0%-fee gateway. Keep signal output clean enough to expose later.

## Start prompt (paste into the new session)
> Read HANDOFF-windows.md and README.md in this folder. Set up the project on this Windows PC, run the tests, fetch 90 days of BTC-USD 1h candles from Coinbase and run a real backtest to confirm stage 1 works. Report the results in plain words, then build stage 2 (paper trading). Follow the hard rules: no real orders, no live trading, no keys in logs.
