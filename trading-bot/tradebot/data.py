"""Candle data: Coinbase public API fetch, CSV cache, and a synthetic generator for tests.

A candle is a tuple-like dict: {"t": unix_seconds, "o","h","l","c","v"}; lists are sorted ascending by t.
"""
import csv
import json
import math
import os
import random
import time
import urllib.request

COINBASE = "https://api.exchange.coinbase.com"
GRANULARITIES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}
FIELDS = ["t", "o", "h", "l", "c", "v"]


def fetch_coinbase(product="BTC-USD", granularity="1h", days=90, now=None, opener=None):
    """Public candles, no key needed. Coinbase returns max 300 per request, so we page backwards."""
    step = GRANULARITIES[granularity]
    end = int(now if now is not None else time.time())
    start_all = end - days * 86400
    opener = opener or (lambda url: urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "tradebot-backtester"}), timeout=20).read())
    out = {}
    cur_end = end
    while cur_end > start_all:
        cur_start = max(start_all, cur_end - 300 * step)
        url = (f"{COINBASE}/products/{product}/candles?granularity={step}"
               f"&start={_iso(cur_start)}&end={_iso(cur_end)}")
        rows = json.loads(opener(url))
        for t, lo, hi, op, cl, vol in rows:  # Coinbase order: time, low, high, open, close, volume
            out[int(t)] = {"t": int(t), "o": op, "h": hi, "l": lo, "c": cl, "v": vol}
        cur_end = cur_start
        time.sleep(0.35)  # stay under the public rate limit
    return [out[k] for k in sorted(out)]


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def save_csv(candles, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for c in candles:
            w.writerow([c[k] for k in FIELDS])


def load_csv(path):
    with open(path, newline="") as f:
        rows = [{k: (int(r[k]) if k == "t" else float(r[k])) for k in FIELDS} for r in csv.DictReader(f)]
    rows.sort(key=lambda c: c["t"])
    for a, b in zip(rows, rows[1:]):
        if a["t"] == b["t"]:
            raise ValueError("duplicate candle timestamp %d" % a["t"])
    return rows


def synthetic(n=2000, step=3600, start=1_700_000_000, seed=1, drift=0.0, vol=0.01, price=30000.0):
    """Random-walk candles for tests and demos. NOT real market data."""
    rng = random.Random(seed)
    out = []
    p = price
    for i in range(n):
        o = p
        p = o * math.exp(drift + vol * rng.gauss(0, 1))
        hi = max(o, p) * (1 + abs(rng.gauss(0, vol / 3)))
        lo = min(o, p) * (1 - abs(rng.gauss(0, vol / 3)))
        out.append({"t": start + i * step, "o": o, "h": hi, "l": lo, "c": p, "v": 100.0})
    return out
