"""Exchange connectors — modular price feeds and trade execution adapters."""
import requests
import time
import logging
from typing import Optional
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

# Simple in-memory price cache (60s TTL)
_price_cache = {}
_CACHE_TTL = 60


def _cached_price(key: str) -> Optional[float]:
    entry = _price_cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["price"]
    return None


def _set_cache(key: str, price: float):
    _price_cache[key] = {"price": price, "ts": time.time()}


# ── Price Feeds (free, no API key needed) ─────────────────────────────────────

def get_price(pair: str, exchange: str = "coingecko") -> Optional[dict]:
    """Get current price for a trading pair. Returns {price, exchange, timestamp}."""
    pair = pair.upper().replace("/", "")
    cached = _cached_price(f"{exchange}:{pair}")
    if cached:
        return {"price": cached, "exchange": exchange, "pair": pair,
                "timestamp": datetime.now(timezone.utc).isoformat(), "cached": True}

    handlers = {
        "coingecko": _price_coingecko,
        "binance": _price_binance,
        "coinbase": _price_coinbase,
    }
    handler = handlers.get(exchange, _price_coingecko)
    try:
        price = handler(pair)
        if price:
            _set_cache(f"{exchange}:{pair}", price)
            return {"price": price, "exchange": exchange, "pair": pair,
                    "timestamp": datetime.now(timezone.utc).isoformat(), "cached": False}
    except Exception as e:
        _log.warning(f"Price fetch failed for {pair} on {exchange}: {e}")

    # Fallback chain
    for fallback in ["coingecko", "binance", "coinbase"]:
        if fallback == exchange:
            continue
        try:
            price = handlers[fallback](pair)
            if price:
                _set_cache(f"{fallback}:{pair}", price)
                return {"price": price, "exchange": fallback, "pair": pair,
                        "timestamp": datetime.now(timezone.utc).isoformat(), "cached": False}
        except Exception:
            continue

    return None


def get_prices(pairs: list, exchange: str = "coingecko") -> dict:
    """Get prices for multiple pairs."""
    results = {}
    for pair in pairs:
        result = get_price(pair, exchange)
        if result:
            results[pair] = result
    return results


def _normalize_symbol(pair: str) -> str:
    """Convert pair formats: BTCUSD -> bitcoin, ETHUSD -> ethereum, etc."""
    mapping = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "DOGE": "dogecoin", "ADA": "cardano", "DOT": "polkadot",
        "AVAX": "avalanche-2", "MATIC": "matic-network", "LINK": "chainlink",
        "UNI": "uniswap", "AAVE": "aave", "ARB": "arbitrum",
        "OP": "optimism", "SUI": "sui", "APT": "aptos",
    }
    # Strip USD/USDC/USDT suffix
    base = pair.replace("USD", "").replace("USDC", "").replace("USDT", "")
    return mapping.get(base, base.lower())


def _price_coingecko(pair: str) -> Optional[float]:
    """Free CoinGecko API — no key needed, 30 calls/min."""
    coin_id = _normalize_symbol(pair)
    r = requests.get(
        f"https://api.coingecko.com/api/v3/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd"},
        timeout=10
    )
    r.raise_for_status()
    data = r.json()
    return data.get(coin_id, {}).get("usd")


def _price_binance(pair: str) -> Optional[float]:
    """Binance public API — no key needed."""
    # Convert BTCUSD -> BTCUSDT for Binance
    symbol = pair.replace("USD", "USDT") if not pair.endswith("USDT") else pair
    r = requests.get(
        f"https://api.binance.com/api/v3/ticker/price",
        params={"symbol": symbol},
        timeout=10
    )
    r.raise_for_status()
    return float(r.json().get("price", 0))


def _price_coinbase(pair: str) -> Optional[float]:
    """Coinbase public API — no key needed."""
    # Convert BTCUSD -> BTC-USD for Coinbase
    base = pair[:3] if len(pair) <= 6 else pair.split("USD")[0]
    r = requests.get(
        f"https://api.coinbase.com/v2/prices/{base}-USD/spot",
        timeout=10
    )
    r.raise_for_status()
    return float(r.json().get("data", {}).get("amount", 0))


# ── Paper Trading Executor ────────────────────────────────────────────────────

class PaperExecutor:
    """Simulated trade execution for paper trading mode."""

    def execute_buy(self, pair: str, quantity: float, price: float = None) -> dict:
        """Simulate a buy order."""
        if not price:
            result = get_price(pair)
            price = result["price"] if result else 0
        return {
            "order_id": f"paper_{int(time.time()*1000)}",
            "pair": pair,
            "side": "buy",
            "quantity": quantity,
            "price": price,
            "total": round(price * quantity, 4),
            "status": "filled",
            "exchange": "paper",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def execute_sell(self, pair: str, quantity: float, price: float = None) -> dict:
        """Simulate a sell order."""
        if not price:
            result = get_price(pair)
            price = result["price"] if result else 0
        return {
            "order_id": f"paper_{int(time.time()*1000)}",
            "pair": pair,
            "side": "sell",
            "quantity": quantity,
            "price": price,
            "total": round(price * quantity, 4),
            "status": "filled",
            "exchange": "paper",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Historical Data (for backtesting) ─────────────────────────────────────────

def get_historical_prices(pair: str, days: int = 30) -> list:
    """Get historical daily prices from CoinGecko (free, no key)."""
    coin_id = _normalize_symbol(pair.upper().replace("/", "").replace("USD", ""))
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        prices = []
        for ts, price in data.get("prices", []):
            prices.append({
                "timestamp": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
                "price": price,
            })
        return prices
    except Exception as e:
        _log.warning(f"Historical data failed for {pair}: {e}")
        return []
