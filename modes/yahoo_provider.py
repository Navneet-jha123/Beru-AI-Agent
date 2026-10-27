"""Yahoo Finance provider — no API key, no quota tracking.
Retention: 1m=7d, 5m/15m/30m=60d, 1h=730d, 1d=unlimited."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Sequence, Tuple
from modes import market_analyst as core


class YahooMarketDataProvider:
    name = "yahoo"
    CACHE_TTL_SECONDS = 60

    INTERVAL_MAP = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "1d": "1d", "1wk": "1wk",
    }
    PERIOD_FOR_INTERVAL = {
        "1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d", "1h": "730d",
        "1d": "5y", "1wk": "10y",
    }

    def __init__(self):
        import time as _time
        self._time = _time
        self._cache = {}  # (market, exchange, symbol, interval) -> (monotonic_ts, candles, source)

    def _yf_symbol(self, market: str, exchange: str, symbol: str) -> str:
        if market == "india":
            return f"{symbol}.NS" if exchange == "NSE" else f"{symbol}.BO"
        return symbol  # US — bare ticker

    def search_instruments(self, query: str, market: str = "auto") -> Sequence[dict]:
        # Yahoo has no official search; return a single best-effort match.
        sym = query.strip().upper()
        results = []
        if market in ("auto", "india"):
            results.append({"name": sym, "symbol": sym, "market": "india",
                            "exchange": "NSE", "primary": True})
        if market in ("auto", "us"):
            results.append({"name": sym, "symbol": sym, "market": "us",
                            "exchange": "US", "primary": market == "us"})
        return results

    def load_candles(self, market: str, exchange: str, symbol: str,
                     interval: str) -> Tuple[Sequence[core.Candle], str]:
        # 60-second cache: repeated calls in the same minute reuse the same data.
        cache_key = (market, exchange, symbol, interval)
        cached = self._cache.get(cache_key)
        if cached and self._time.monotonic() - cached[0] < self.CACHE_TTL_SECONDS:
            return cached[1], cached[2]

        try:
            import yfinance as yf
        except ImportError:
            raise core.MarketDataError("yfinance not installed. Run: pip install yfinance")

        if interval not in self.INTERVAL_MAP:
            raise core.MarketDataError(f"Yahoo does not support interval '{interval}'.")

        yf_sym = self._yf_symbol(market, exchange, symbol)
        period = self.PERIOD_FOR_INTERVAL[interval]
        try:
            df = yf.Ticker(yf_sym).history(period=period, interval=interval, auto_adjust=False)
        except Exception as exc:
            raise core.MarketDataError(f"Yahoo fetch failed for {yf_sym}: {exc}") from None

        if df.empty:
            raise core.MarketDataError(
                f"Yahoo returned no bars for {yf_sym} ({interval}, {period}). "
                f"Check the symbol suffix (.NS for NSE, .BO for BSE)."
            )

        candles = []
        for ts, row in df.iterrows():
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            try:
                c = core.Candle(ts, float(row["Open"]), float(row["High"]),
                                float(row["Low"]), float(row["Close"]),
                                float(row.get("Volume", 0) or 0))
            except (KeyError, TypeError, ValueError):
                continue
            if c.open <= 0 or c.high < c.low:
                continue
            candles.append(c)

        if not candles:
            raise core.MarketDataError(f"All Yahoo rows for {yf_sym} were malformed.")
        candles.sort(key=lambda c: c.timestamp)
        result = (tuple(candles[-core.MAX_BARS:]), f"Yahoo Finance ({yf_sym}, {interval})")
        self._cache[cache_key] = (self._time.monotonic(), result[0], result[1])
        return result