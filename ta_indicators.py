"""Technical Analysis indicators — pure Python, no external dependencies."""
from typing import List, Optional


def sma(prices: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average."""
    result = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        result[i] = sum(prices[i - period + 1:i + 1]) / period
    return result


def ema(prices: List[float], period: int) -> List[Optional[float]]:
    """Exponential Moving Average."""
    result = [None] * len(prices)
    if len(prices) < period:
        return result
    k = 2 / (period + 1)
    result[period - 1] = sum(prices[:period]) / period
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)
    return result


def rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index (Wilder's smoothing)."""
    result = [None] * len(prices)
    if len(prices) < period + 1:
        return result
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))
    for i in range(period + 1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gain = max(delta, 0)
        loss = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100 - (100 / (1 + rs))
    return result


def bollinger_bands(prices: List[float], period: int = 20, num_std: float = 2.0):
    """Bollinger Bands — returns (upper, middle, lower) lists."""
    middle = sma(prices, period)
    upper = [None] * len(prices)
    lower = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1:i + 1]
        mean = middle[i]
        variance = sum((p - mean) ** 2 for p in window) / period
        std = variance ** 0.5
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std
    return upper, middle, lower


def macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD — returns (macd_line, signal_line, histogram) lists."""
    fast_ema = ema(prices, fast)
    slow_ema = ema(prices, slow)
    macd_line = [None] * len(prices)
    for i in range(len(prices)):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            macd_line[i] = fast_ema[i] - slow_ema[i]
    macd_values = [v for v in macd_line if v is not None]
    if len(macd_values) < signal:
        return macd_line, [None] * len(prices), [None] * len(prices)
    signal_line = [None] * len(prices)
    start_idx = next(i for i, v in enumerate(macd_line) if v is not None)
    sig_ema = ema(macd_values, signal)
    for j, val in enumerate(sig_ema):
        if val is not None:
            signal_line[start_idx + j] = val
    histogram = [None] * len(prices)
    for i in range(len(prices)):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]
    return macd_line, signal_line, histogram


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Average True Range — approximated from close prices when OHLC not available."""
    if len(highs) != len(lows) or len(highs) != len(closes):
        return [None] * len(closes)
    tr = [None] * len(closes)
    for i in range(1, len(closes)):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        tr[i] = max(h_l, h_pc, l_pc)
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result
    first_atr = sum(v for v in tr[1:period + 1] if v is not None) / period
    result[period] = first_atr
    for i in range(period + 1, len(closes)):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result


def vwap_proxy(prices: List[float], volumes: List[float] = None) -> List[Optional[float]]:
    """VWAP proxy — if no volumes, use equal-weighted cumulative average."""
    if not volumes:
        result = [None] * len(prices)
        cumsum = 0
        for i, p in enumerate(prices):
            cumsum += p
            result[i] = cumsum / (i + 1)
        return result
    result = [None] * len(prices)
    cum_pv = 0
    cum_v = 0
    for i in range(len(prices)):
        cum_pv += prices[i] * volumes[i]
        cum_v += volumes[i]
        result[i] = cum_pv / cum_v if cum_v > 0 else None
    return result


def stochastic(prices: List[float], k_period: int = 14, d_period: int = 3):
    """Stochastic Oscillator — returns (%K, %D) lists."""
    k_values = [None] * len(prices)
    for i in range(k_period - 1, len(prices)):
        window = prices[i - k_period + 1:i + 1]
        low = min(window)
        high = max(window)
        if high == low:
            k_values[i] = 50.0
        else:
            k_values[i] = ((prices[i] - low) / (high - low)) * 100
    d_values = sma([v if v is not None else 0 for v in k_values], d_period)
    for i in range(len(d_values)):
        if k_values[i] is None:
            d_values[i] = None
    return k_values, d_values


# ── Signal Generation ────────────────────────────────────────────────────────

def generate_signals(prices: List[float], strategy_type: str, config: dict) -> List[dict]:
    """Generate buy/sell signals based on strategy type and config.

    Returns list of {index, signal, reason} where signal is 'buy', 'sell', or 'hold'.
    """
    if strategy_type == "momentum":
        return _signals_momentum(prices, config)
    elif strategy_type == "mean_reversion":
        return _signals_mean_reversion(prices, config)
    elif strategy_type == "dca":
        return _signals_dca(prices, config)
    elif strategy_type == "arbitrage":
        return [{"index": i, "signal": "hold", "reason": "requires multi-exchange"} for i in range(len(prices))]
    elif strategy_type == "sentiment":
        return [{"index": i, "signal": "hold", "reason": "requires sentiment feed"} for i in range(len(prices))]
    return [{"index": i, "signal": "hold", "reason": "unknown strategy"} for i in range(len(prices))]


def _signals_momentum(prices: List[float], config: dict) -> List[dict]:
    fast_period = config.get("fast_period", 10)
    slow_period = config.get("slow_period", 30)
    entry_threshold = config.get("entry_threshold", 0.02)
    exit_threshold = config.get("exit_threshold", -0.01)
    fast_ma = sma(prices, fast_period)
    slow_ma = sma(prices, slow_period)
    signals = []
    for i in range(len(prices)):
        if fast_ma[i] is None or slow_ma[i] is None:
            signals.append({"index": i, "signal": "hold", "reason": "warming up"})
            continue
        spread = (fast_ma[i] - slow_ma[i]) / slow_ma[i]
        if spread > entry_threshold:
            signals.append({"index": i, "signal": "buy", "reason": f"fast MA crossed above slow ({spread:.3f})"})
        elif spread < exit_threshold:
            signals.append({"index": i, "signal": "sell", "reason": f"fast MA crossed below slow ({spread:.3f})"})
        else:
            signals.append({"index": i, "signal": "hold", "reason": f"neutral spread ({spread:.3f})"})
    return signals


def _signals_mean_reversion(prices: List[float], config: dict) -> List[dict]:
    rsi_period = config.get("rsi_period", 14)
    rsi_oversold = config.get("rsi_oversold", 30)
    rsi_overbought = config.get("rsi_overbought", 70)
    bb_period = config.get("bb_period", 20)
    bb_std = config.get("bb_std", 2.0)
    rsi_vals = rsi(prices, rsi_period)
    bb_upper, bb_mid, bb_lower = bollinger_bands(prices, bb_period, bb_std)
    signals = []
    for i in range(len(prices)):
        if rsi_vals[i] is None or bb_lower[i] is None:
            signals.append({"index": i, "signal": "hold", "reason": "warming up"})
            continue
        reasons = []
        score = 0
        if rsi_vals[i] < rsi_oversold:
            score += 1
            reasons.append(f"RSI oversold ({rsi_vals[i]:.1f})")
        elif rsi_vals[i] > rsi_overbought:
            score -= 1
            reasons.append(f"RSI overbought ({rsi_vals[i]:.1f})")
        if prices[i] < bb_lower[i]:
            score += 1
            reasons.append("below lower BB")
        elif prices[i] > bb_upper[i]:
            score -= 1
            reasons.append("above upper BB")
        if score >= 1:
            signals.append({"index": i, "signal": "buy", "reason": "; ".join(reasons)})
        elif score <= -1:
            signals.append({"index": i, "signal": "sell", "reason": "; ".join(reasons)})
        else:
            signals.append({"index": i, "signal": "hold", "reason": "neutral"})
    return signals


def _signals_dca(prices: List[float], config: dict) -> List[dict]:
    interval = max(int(config.get("interval_hours", 24)), 1)
    signals = []
    for i in range(len(prices)):
        if i % interval == 0:
            signals.append({"index": i, "signal": "buy", "reason": f"DCA interval ({interval}h)"})
        else:
            signals.append({"index": i, "signal": "hold", "reason": "between intervals"})
    return signals
