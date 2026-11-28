import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from tradebot import data, backtest, strategy, cli


def flat(prices, step=3600):
    return [{"t": i * step, "o": p, "h": p, "l": p, "c": p, "v": 1} for i, p in enumerate(prices)]


def test_no_lookahead_signals_causal():
    c = data.synthetic(500, seed=3)
    for s in (strategy.MACross(5, 20), strategy.RSIReversion(14, 35, 55)):
        full = s.positions(c)
        for k in (60, 200, 333):
            assert s.positions(c[:k]) == full[:k]


def test_fill_at_next_open_with_fees():
    c = flat([100, 100, 110, 110])
    r = backtest.run(c, [1, 1, 0, 0], capital=1000, fee=0.01, slippage_bps=0)
    t = r.trades[0]
    assert t.entry_price == 100 and t.exit_price == 110  # buy at open of bar1, sell at open of bar3
    # 1000 -> qty=1000/(100*1.01); sell proceeds minus 1% fee
    qty = 1000 / 101
    assert r.metrics["end_equity"] == pytest.approx(qty * 110 * 0.99, rel=1e-9)
    assert r.metrics["fees_paid"] == pytest.approx(qty * 100 * 0.01 + qty * 110 * 0.01)


def test_open_position_closed_at_end_and_equity_matches():
    c = flat([100, 100, 100, 120])
    r = backtest.run(c, [1, 1, 1, 1], capital=1000, fee=0, slippage_bps=0)
    assert len(r.trades) == 1 and r.metrics["end_equity"] == pytest.approx(1200)
    assert r.equity[-1][1] == pytest.approx(1200)


def test_slippage_hurts():
    c = flat([100, 100, 100, 100])
    r = backtest.run(c, [1, 1, 0, 0], capital=1000, fee=0, slippage_bps=100)
    assert r.metrics["end_equity"] < 1000


def test_drawdown_and_winrate():
    c = flat([100, 100, 50, 50, 100, 100])
    r = backtest.run(c, [1, 1, 1, 0, 0, 0], capital=1000, fee=0, slippage_bps=0)
    assert r.metrics["max_drawdown_pct"] == pytest.approx(50)
    assert r.metrics["win_rate_pct"] == 0.0


def test_input_validation():
    with pytest.raises(ValueError):
        backtest.run(flat([1, 2, 3]), [1, 1], 100)
    with pytest.raises(ValueError):
        strategy.MACross(50, 20)


def test_csv_roundtrip_and_duplicates(tmp_path):
    c = data.synthetic(20)
    p = str(tmp_path / "c.csv")
    data.save_csv(c, p)
    assert [x["c"] for x in data.load_csv(p)] == pytest.approx([x["c"] for x in c])
    data.save_csv(c + [c[-1]], p)
    with pytest.raises(ValueError):
        data.load_csv(p)


def test_fetch_pages_and_orders_candles():
    calls = []
    def opener(url):
        calls.append(url)
        # one candle per request, Coinbase column order: time, low, high, open, close, volume
        n = len(calls)
        return ('[[%d, 1, 3, 2, 2.5, 9]]' % (1000 - n * 10)).encode()
    out = data.fetch_coinbase("BTC-USD", "1h", days=1, now=1_000_000, opener=opener)
    assert len(calls) >= 1 and out == sorted(out, key=lambda c: c["t"])
    assert out[0]["o"] == 2 and out[0]["h"] == 3 and out[0]["l"] == 1 and out[0]["c"] == 2.5


def test_cli_end_to_end(tmp_path, capsys):
    rc = cli.main(["backtest", "--synthetic", "--out", str(tmp_path)])
    assert rc == 0
    assert "Not financial advice" in capsys.readouterr().out
    assert (tmp_path / "BTC-USD_1h_ma_cross.png").exists()
    assert (tmp_path / "BTC-USD_1h_ma_cross_trades.csv").exists()
