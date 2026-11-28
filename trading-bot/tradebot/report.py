import csv
import os

DISCLAIMER = ("Historical simulation only. Past results do not predict future results; backtests can be "
              "overfit, and real fills differ. Not financial advice.")


def write_trades(result, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["entry_t", "entry_price", "exit_t", "exit_price", "qty", "fees", "pnl", "return"])
        for t in result.trades:
            w.writerow([t.entry_t, t.entry_price, t.exit_t, t.exit_price, t.qty, t.fees, t.pnl, t.ret])


def format_metrics(m):
    return "\n".join([
        f"Return:        {m['total_return_pct']:+.2f}%   (buy & hold {m['buy_hold_return_pct']:+.2f}%)",
        f"Max drawdown:  {m['max_drawdown_pct']:.2f}%",
        f"Sharpe (ann.): {m['sharpe']:.2f}",
        f"Trades:        {m['trades']}   win rate {m['win_rate_pct']:.1f}%",
        f"Fees paid:     {m['fees_paid']:.2f}",
        f"End equity:    {m['end_equity']:.2f} (start {m['start_capital']:.2f})",
        DISCLAIMER])


def chart(candles, result, path, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from datetime import datetime, timezone
    ts = [datetime.fromtimestamp(c["t"], timezone.utc) for c in candles]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    a1.plot(ts, [c["c"] for c in candles], lw=0.8, color="#555")
    for t in result.trades:
        a1.axvline(datetime.fromtimestamp(t.entry_t, timezone.utc), color="#2a9d4a", alpha=.25, lw=.8)
        a1.axvline(datetime.fromtimestamp(t.exit_t, timezone.utc), color="#d33", alpha=.25, lw=.8)
    a1.set_title(title + " price (green=entry, red=exit)")
    a2.plot(ts, [e for _, e in result.equity], color="#1f6feb")
    a2.set_title("Equity (simulated)")
    fig.text(0.5, 0.005, DISCLAIMER, ha="center", fontsize=7)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
