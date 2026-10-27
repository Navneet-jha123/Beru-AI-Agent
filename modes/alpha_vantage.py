"""Native Alpha Vantage adapter for BERU's validated OHLCV provider interface.

The free-key path uses global daily/weekly historical time series. Intraday endpoints
are deliberately not requested by this adapter because free entitlements do not
provide BERU's expected intraday workflow.
"""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, time as clock_time
from typing import Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from threading import Lock
from zoneinfo import ZoneInfo


class AlphaVantageMarketDataProvider:
    name = "alpha_vantage"
    endpoint = "https://www.alphavantage.co/query"
    max_response_bytes = 8 * 1024 * 1024

    def __init__(self, api_key: str):
        self.api_key = (api_key or "").strip()
        if not self.api_key or len(self.api_key) > 256:
            from modes.market_analyst import MarketDataError
            raise MarketDataError("ALPHA_VANTAGE_API_KEY is missing or invalid.")
        self._cache = {}
        self._search_cache = {}
        self._request_lock = Lock()
        self._last_request = 0.0

    def _request(self, params: dict) -> dict:
        from modes import market_analyst as core

        query = dict(params)
        query["apikey"] = self.api_key
        request = Request(
            self.endpoint + "?" + urlencode(query),
            headers={"Accept": "application/json", "User-Agent": "BERU-Market-Analyst/1.0"},
            method="GET",
        )
        try:
            with build_opener(core._NoRedirectHandler()).open(request, timeout=15) as response:
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise core.MarketDataError(
                f"Alpha Vantage returned HTTP {exc.code}; check the key, quota, and API access."
            ) from None
        except (URLError, TimeoutError, OSError):
            raise core.MarketDataError("Could not reach Alpha Vantage (network or timeout).") from None
        if len(raw) > self.max_response_bytes:
            raise core.MarketDataError("Alpha Vantage response exceeds the configured size limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise core.MarketDataError("Alpha Vantage returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise core.MarketDataError("Alpha Vantage response must be a JSON object.")
        message = payload.get("Error Message") or payload.get("Note") or payload.get("Information")
        if message:
            safe_message = str(message).replace(self.api_key, "[redacted]")[:240]
            raise core.MarketDataError(f"Alpha Vantage: {safe_message}")
        return payload

    def search_instruments(self, query: str, market: str = "auto") -> Sequence[dict]:
        payload = self._request({"function": "SYMBOL_SEARCH", "keywords": query})
        matches = payload.get("bestMatches", [])
        if not isinstance(matches, list):
            from modes.market_analyst import MarketDataError
            raise MarketDataError("Alpha Vantage symbol search returned an unexpected response.")
        out = []
        for row in matches[:10]:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("1. symbol", "")).strip().upper()
            name = str(row.get("2. name", "")).strip()[:120]
            region = str(row.get("4. region", "")).strip().casefold()
            if not symbol or not name:
                continue
            if region.startswith("india"):
                market_key = "india"
                suffix = symbol.rsplit(".", 1)[-1] if "." in symbol else ""
                exchange = {"BSE": "BSE", "NSE": "NSE"}.get(suffix)
                if not exchange:
                    continue
            elif region in {"united states", "usa", "united states of america"}:
                market_key, exchange = "us", "US"
            else:
                continue
            try:
                score = float(row.get("9. matchScore", 0) or 0)
            except (TypeError, ValueError):
                score = 0.0
            out.append({
                "name": name, "symbol": symbol, "market": market_key,
                "exchange": exchange, "primary": score >= 0.99,
            })
        return out

    def load_candles(self, market: str, exchange: str, symbol: str,
                     interval: str) -> Tuple[Sequence[object], str]:
        from modes import market_analyst as core

        if interval not in {"1d", "1wk"}:
            raise core.MarketDataError(
                "Alpha Vantage is configured for daily/weekly historical data. "
                "This free-key adapter does not provide intraday candles; choose 1d or 1wk."
            )
        provider_symbol = symbol
        if market == "india" and not symbol.endswith((".BSE", ".NSE")):
            provider_symbol = f"{symbol}.{exchange}"
        cache_key = (market, exchange, provider_symbol, interval)
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 900:
            return cached[1], cached[2]
        if interval == "1d":
            function, series_key = "TIME_SERIES_DAILY", "Time Series (Daily)"
        else:
            function, series_key = "TIME_SERIES_WEEKLY", "Weekly Time Series"
        payload = self._request({
            "function": function, "symbol": provider_symbol, "outputsize": "compact",
        })
        series = payload.get(series_key)
        if not isinstance(series, dict) or not series:
            raise core.MarketDataError(
                "Alpha Vantage returned no candles for this symbol. Check its exact listing "
                "with symbol search and confirm the key's data entitlement."
            )
        zone = ZoneInfo("Asia/Kolkata" if market == "india" else "America/New_York")
        candles = []
        for stamp, values in series.items():
            if not isinstance(values, dict):
                continue
            try:
                local_date = date.fromisoformat(str(stamp))
                timestamp = datetime.combine(local_date, clock_time(16, 0), tzinfo=zone)
                now_local = datetime.now(zone)
                close_time = clock_time(16, 0) if market == "india" else clock_time(16, 30)
                is_current_bar = (local_date == now_local.date() if interval == "1d" else
                                  local_date.isocalendar()[:2] == now_local.date().isocalendar()[:2])
                if is_current_bar and now_local.timetz().replace(tzinfo=None) < close_time:
                    continue
                candle = core.Candle(
                    timestamp, float(values["1. open"]), float(values["2. high"]),
                    float(values["3. low"]), float(values["4. close"]),
                    float(values["5. volume"]),
                )
            except (ValueError, TypeError, KeyError, OverflowError):
                raise core.MarketDataError("Alpha Vantage returned a malformed OHLCV row.") from None
            numeric = (candle.open, candle.high, candle.low, candle.close, candle.volume)
            if not all(math.isfinite(value) for value in numeric):
                raise core.MarketDataError("Alpha Vantage returned non-finite candle data.")
            if min(numeric[:4]) <= 0 or candle.volume < 0:
                raise core.MarketDataError("Alpha Vantage returned invalid price or volume values.")
            if candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(candle.open, candle.close):
                raise core.MarketDataError("Alpha Vantage returned inconsistent OHLC values.")
            candles.append(candle)
        candles.sort(key=lambda candle: candle.timestamp)
        candles = candles[-core.MAX_BARS:]
        if len({candle.timestamp for candle in candles}) != len(candles):
            raise core.MarketDataError("Alpha Vantage returned duplicate candle timestamps.")
        result = (tuple(candles), "Alpha Vantage daily/weekly OHLCV")
        self._cache[cache_key] = (time.monotonic(), result[0], result[1])
        return result
