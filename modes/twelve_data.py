"""Optional Twelve Data adapter for BERU's normalized OHLCV interface.

Provider entitlements vary by plan and exchange. This adapter never implies that
an instrument or interval is included in the account's plan.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo


class TwelveDataMarketDataProvider:
    name = "twelve_data"
    endpoint = "https://api.twelvedata.com"
    max_response_bytes = 8 * 1024 * 1024
    intervals = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
                 "1h": "1h", "1d": "1day", "1wk": "1week"}
    exchanges = {"NSE": "NSE", "BSE": "BSE"}

    def __init__(self, api_key: str):
        self.api_key = (api_key or "").strip()
        if not self.api_key or len(self.api_key) > 256:
            from modes.market_analyst import MarketDataError
            raise MarketDataError("TWELVE_DATA_API_KEY is missing or invalid.")
        self._cache = {}
        self._search_cache = {}

    def _request(self, endpoint: str, params: dict) -> dict:
        from modes.market_analyst import MarketDataError
        query = dict(params)
        query["apikey"] = self.api_key
        request = Request(f"{self.endpoint}/{endpoint}?{urlencode(query)}",
                          headers={"Accept": "application/json", "User-Agent": "BERU-Market-Analyst/1.0"})
        try:
            with build_opener().open(request, timeout=15) as response:
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise MarketDataError(f"Twelve Data returned HTTP {exc.code}; check key, quota, and entitlement.") from None
        except (URLError, TimeoutError, OSError):
            raise MarketDataError("Could not reach Twelve Data (network or timeout).") from None
        if len(raw) > self.max_response_bytes:
            raise MarketDataError("Twelve Data response exceeds BERU's size limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MarketDataError("Twelve Data returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise MarketDataError("Twelve Data returned an unexpected response.")
        if payload.get("status") == "error" or payload.get("code"):
            message = str(payload.get("message", "Provider rejected the request."))[:220]
            raise MarketDataError(f"Twelve Data: {message}")
        return payload

    def search_instruments(self, query: str, market: str = "auto") -> Sequence[dict]:
        from modes.market_analyst import MarketDataError
        key = (query.casefold().strip(), market.casefold().strip())
        if key in self._search_cache:
            return self._search_cache[key]
        payload = self._request("symbol_search", {"symbol": query, "outputsize": 10})
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise MarketDataError("Twelve Data symbol search returned an unexpected response.")
        results = []
        seen = set()
        for row in rows[:20]:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol", "")).strip().upper()
            name = str(row.get("instrument_name", row.get("name", symbol))).strip()[:120]
            exchange_raw = str(row.get("exchange", "")).strip().upper()
            country = str(row.get("country", "")).strip().casefold()
            if country in {"india", "in"}:
                mk = "india"
                ex = "NSE" if exchange_raw in {"NSE", "NATIONAL STOCK EXCHANGE OF INDIA"} else "BSE" if exchange_raw in {"BSE", "BOMBAY STOCK EXCHANGE", "BOMBAY STOCK EXCHANGE LTD"} else ""
            elif country in {"united states", "usa", "us"}:
                mk, ex = "us", "US"
            else:
                continue
            if market not in {"auto", ""} and mk != market:
                continue
            if not symbol or not ex:
                continue
            unique = (mk, ex, symbol)
            if unique in seen:
                continue
            seen.add(unique)
            results.append({"name": name, "symbol": symbol, "market": mk,
                            "exchange": ex, "primary": False})
        out = tuple(results)
        self._search_cache[key] = out
        return out

    def load_candles(self, market: str, exchange: str, symbol: str,
                     interval: str) -> Tuple[Sequence[object], str]:
        from modes import market_analyst as core
        if interval not in self.intervals:
            raise core.MarketDataError(f"Twelve Data interval {interval} is not supported by BERU.")
        cache_key = (market, exchange, symbol, interval)
        cached = self._cache.get(cache_key)
        ttl = 30 if interval in {"1m", "5m", "15m", "30m", "1h"} else 300
        if cached and __import__("time").monotonic() - cached[0] < ttl:
            return cached[1], cached[2]
        params = {"symbol": symbol, "interval": self.intervals[interval], "outputsize": 5000}
        if market == "india":
            params["exchange"] = self.exchanges[exchange]
        elif exchange != "US":
            params["exchange"] = exchange
        payload = self._request("time_series", params)
        rows = payload.get("values")
        if not isinstance(rows, list) or not rows:
            raise core.MarketDataError("Twelve Data returned no candles for this symbol/interval; verify symbol and account entitlement.")
        zone = ZoneInfo("Asia/Kolkata" if market == "india" else "America/New_York")
        candles = []
        for i, row in enumerate(rows[:core.MAX_BARS], 1):
            try:
                raw = datetime.fromisoformat(str(row["datetime"]).replace("Z", "+00:00"))
                stamp = raw.replace(tzinfo=zone) if raw.tzinfo is None else raw
                candle = core.Candle(stamp, float(row["open"]), float(row["high"]),
                                     float(row["low"]), float(row["close"]), float(row.get("volume", 0)))
            except (KeyError, TypeError, ValueError, OverflowError):
                raise core.MarketDataError(f"Twelve Data candle {i} is malformed.") from None
            values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
            if not all(math.isfinite(v) for v in values) or min(values[:4]) <= 0 or candle.volume < 0:
                raise core.MarketDataError(f"Twelve Data candle {i} contains invalid numeric values.")
            if candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(candle.open, candle.close):
                raise core.MarketDataError(f"Twelve Data candle {i} has inconsistent OHLC values.")
            candles.append(candle)
        candles.sort(key=lambda c: c.timestamp)
        if len({c.timestamp for c in candles}) != len(candles):
            raise core.MarketDataError("Twelve Data returned duplicate candle timestamps.")
        meta = payload.get("meta", {})
        source = "Twelve Data OHLCV"
        if isinstance(meta, dict) and meta.get("exchange"):
            source += f" ({str(meta['exchange'])[:60]})"
        result = (tuple(candles), source)
        self._cache[cache_key] = (__import__("time").monotonic(), result[0], result[1])
        return result
