import argparse
import os
from . import data, backtest, report, strategy

BPY = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760, "6h": 1460, "1d": 365}


def main(argv=None):
    p = argparse.ArgumentParser(prog="tradebot", description="Backtester (historical simulation, not advice)")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download candles from Coinbase's public API into data/")
    f.add_argument("--product", default="BTC-USD")
    f.add_argument("--granularity", default="1h", choices=list(data.GRANULARITIES))
    f.add_argument("--days", type=int, default=90)
    r = sub.add_parser("backtest", help="run a strategy over a candle CSV")
    r.add_argument("--csv", help="candle CSV (default: data/<product>_<gran>.csv)")
    r.add_argument("--product", default="BTC-USD")
    r.add_argument("--granularity", default="1h", choices=list(data.GRANULARITIES))
    r.add_argument("--strategy", default="ma_cross", choices=list(strategy.REGISTRY))
    r.add_argument("--param", action="append", default=[], help="name=value, repeatable")
    r.add_argument("--fee", type=float, default=0.006, help="per-side fee fraction (default 0.6%%)")
    r.add_argument("--slippage-bps", type=float, default=5.0)
    r.add_argument("--capital", type=float, default=10000.0)
    r.add_argument("--out", default="results")
    r.add_argument("--synthetic", action="store_true", help="use random-walk demo data (NOT real)")
    a = p.parse_args(argv)

    path = lambda: f"data/{a.product}_{a.granularity}.csv"
    if a.cmd == "fetch":
        c = data.fetch_coinbase(a.product, a.granularity, a.days)
        data.save_csv(c, path())
        print(f"saved {len(c)} candles to {path()}")
        return 0
    candles = data.synthetic(step=data.GRANULARITIES[a.granularity]) if a.synthetic \
        else data.load_csv(a.csv or path())
    params = dict(kv.split("=", 1) for kv in a.param)
    strat = strategy.REGISTRY[a.strategy](**{k: float(v) if "." in v else int(v) for k, v in params.items()})
    res = backtest.run(candles, strat.positions(candles), a.capital, a.fee, a.slippage_bps, BPY[a.granularity])
    tag = f"{a.product}_{a.granularity}_{a.strategy}"
    report.write_trades(res, os.path.join(a.out, tag + "_trades.csv"))
    report.chart(candles, res, os.path.join(a.out, tag + ".png"), tag)
    print(report.format_metrics(res.metrics))
    print(f"trade log + chart in {a.out}/")
    return 0
