"""Strategies are plug-ins. A strategy maps candles -> a list of target positions (0 flat, 1 long),
one per candle, where position[i] may only use candles[0..i] (checked by tests). The engine fills
a change of target at the NEXT candle's open, so there is no look-ahead.

MA cross and RSI below are EXAMPLES to exercise the backtester, not recommendations."""
REGISTRY = {}


def register(name):
    def deco(cls):
        REGISTRY[name] = cls
        return cls
    return deco


class Strategy:
    name = "base"

    def positions(self, candles):
        raise NotImplementedError


def sma(values, n):
    out, s = [None] * len(values), 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rsi(values, n=14):
    out = [None] * len(values)
    if len(values) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


@register("ma_cross")
class MACross(Strategy):
    """Example: long while the fast SMA is above the slow SMA."""
    name = "ma_cross"

    def __init__(self, fast=20, slow=50):
        if fast >= slow:
            raise ValueError("fast must be < slow")
        self.fast, self.slow = int(fast), int(slow)

    def positions(self, candles):
        c = [x["c"] for x in candles]
        f, s = sma(c, self.fast), sma(c, self.slow)
        return [1 if (a is not None and b is not None and a > b) else 0 for a, b in zip(f, s)]


@register("rsi_reversion")
class RSIReversion(Strategy):
    """Example: buy when RSI < low, hold until RSI > high."""
    name = "rsi_reversion"

    def __init__(self, period=14, low=30, high=55):
        self.period, self.low, self.high = int(period), float(low), float(high)

    def positions(self, candles):
        r = rsi([x["c"] for x in candles], self.period)
        pos, cur = [], 0
        for v in r:
            if v is not None:
                if cur == 0 and v < self.low:
                    cur = 1
                elif cur == 1 and v > self.high:
                    cur = 0
            pos.append(cur)
        return pos
