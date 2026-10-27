"""Read-only, provider-neutral stock analysis for India and US equities.

The initial provider reads user-supplied OHLCV CSV exports from workspace/market_data.
No quote is fetched from the web and no order can be placed. A licensed market-data
adapter can later implement MarketDataProvider without changing the analysis engine.
"""
from __future__ import annotations

import csv
import json
import os
import math
import re
import time
from statistics import median
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from typing import List, Optional, Protocol, Sequence, Tuple

from config import WORKSPACE_DIR

MARKET_DATA_DIR = WORKSPACE_DIR / "market_data"
MAX_CSV_BYTES = 20 * 1024 * 1024
MAX_BARS = 10_000
MINIMUM_BARS = {"intraday": 30, "swing": 60, "long_term": 200}
ALLOWED_INTERVALS = {"intraday": {"1m", "5m", "15m", "30m", "1h"},
                     "swing": {"1d"}, "long_term": {"1d", "1wk"}}
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")
_INTERVAL_RE = re.compile(r"^(1m|5m|15m|30m|1h|1d|1wk)$")


class MarketDataError(ValueError):
    """Raised when data is unavailable or fails validation."""


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataProvider(Protocol):
    """Provider contract shared by CSV, configured HTTP/JSON, and licensed adapters."""
    name: str

    def load_candles(self, market: str, exchange: str, symbol: str,
                     interval: str) -> Tuple[Sequence[Candle], str]: ...


def _normalize_inputs(market: str, exchange: str, symbol: str, interval: str,
                      horizon: str) -> Tuple[str, str, str, str, str]:
    market_aliases = {"india": "india", "in": "india", "nse": "india", "bse": "india",
                      "us": "us", "usa": "us", "united states": "us"}
    market_key = market_aliases.get((market or "").strip().lower(), "")
    if not market_key:
        raise MarketDataError("Market must be India or US.")
    exchange_key = (exchange or ("NSE" if market_key == "india" else "NASDAQ")).strip().upper()
    valid_exchanges = {"india": {"NSE", "BSE"}, "us": {"NYSE", "NASDAQ", "AMEX", "US"}}
    if exchange_key not in valid_exchanges[market_key]:
        raise MarketDataError(f"Unsupported exchange '{exchange_key}' for {market_key.upper()}; "
                              f"choose {', '.join(sorted(valid_exchanges[market_key]))}.")
    symbol_key = (symbol or "").strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol_key) or ".." in symbol_key:
        raise MarketDataError("Ticker must use letters, digits, dot, underscore, or hyphen (max 30 characters).")
    horizon_key = (horizon or "").strip().lower().replace("-", "_").replace(" ", "_")
    horizon_aliases = {"day_trade": "intraday", "day_trading": "intraday", "regular": "swing",
                       "positional": "swing", "position": "swing", "longterm": "long_term",
                       "long_term_investing": "long_term", "investing": "long_term"}
    horizon_key = horizon_aliases.get(horizon_key, horizon_key)
    if horizon_key not in ALLOWED_INTERVALS:
        raise MarketDataError("Horizon must be intraday, swing/regular, or long_term.")
    interval_key = (interval or ("5m" if horizon_key == "intraday" else "1d")).strip().lower()
    if not _INTERVAL_RE.fullmatch(interval_key) or interval_key not in ALLOWED_INTERVALS[horizon_key]:
        allowed = ", ".join(sorted(ALLOWED_INTERVALS[horizon_key]))
        raise MarketDataError(f"Interval '{interval_key}' does not fit {horizon_key}; allowed: {allowed}.")
    return market_key, exchange_key, symbol_key, interval_key, horizon_key


def _parse_timestamp(raw: str) -> datetime:
    value = (raw or "").strip()
    if not value:
        raise MarketDataError("A timestamp cell is empty.")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketDataError(f"Invalid timestamp '{value[:40]}'; use ISO 8601 with a UTC offset.") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MarketDataError(f"Timestamp '{value[:40]}' has no UTC offset; use ISO 8601 with timezone, "
                              "for example 2026-10-23T09:30:00-04:00 or 2026-10-23T09:15:00+05:30.")
    return dt


class CsvMarketDataProvider:
    """Reads user-owned OHLCV files; never accesses the network."""
    name = "local_csv"

    def __init__(self, data_dir: Path = MARKET_DATA_DIR):
        self.data_dir = Path(data_dir).resolve()

    def expected_path(self, market: str, exchange: str, symbol: str, interval: str) -> Path:
        candidate = (self.data_dir / f"{market}_{exchange}_{symbol}_{interval}.csv").resolve()
        if not candidate.is_relative_to(self.data_dir):
            raise MarketDataError("Data file path failed workspace containment validation.")
        return candidate

    def load_candles(self, market: str, exchange: str, symbol: str,
                     interval: str) -> Tuple[Sequence[Candle], str]:
        path = self.expected_path(market, exchange, symbol, interval)
        if not path.is_file():
            raise MarketDataError(
                f"No local dataset found for {market.upper()} {exchange}:{symbol} ({interval}). "
                f"Export OHLCV candles from a data source you trust to '{path}'. "
                "Required columns: timestamp,open,high,low,close,volume. No live data provider is configured."
            )
        if path.stat().st_size > MAX_CSV_BYTES:
            raise MarketDataError(f"CSV exceeds the {MAX_CSV_BYTES // (1024 * 1024)} MB size limit.")
        rows: List[Candle] = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise MarketDataError("CSV has no header row.")
                reader.fieldnames = [str(n).strip().lower() for n in reader.fieldnames]
                needed = {"timestamp", "open", "high", "low", "close", "volume"}
                missing = sorted(needed - set(reader.fieldnames))
                if missing:
                    raise MarketDataError("CSV is missing required columns: " + ", ".join(missing))
                for line_no, row in enumerate(reader, start=2):
                    if len(rows) >= MAX_BARS:
                        raise MarketDataError(f"CSV exceeds the {MAX_BARS:,}-bar limit.")
                    try:
                        candle = Candle(_parse_timestamp(row.get("timestamp", "")),
                                        float(row.get("open", "")), float(row.get("high", "")),
                                        float(row.get("low", "")), float(row.get("close", "")),
                                        float(row.get("volume", "")))
                    except (TypeError, ValueError) as exc:
                        if isinstance(exc, MarketDataError):
                            raise
                        raise MarketDataError(f"Invalid numeric candle value on CSV line {line_no}.") from exc
                    values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
                    if not all(math.isfinite(v) for v in values):
                        raise MarketDataError(f"Non-finite number on CSV line {line_no}.")
                    if min(candle.open, candle.high, candle.low, candle.close) <= 0 or candle.volume < 0:
                        raise MarketDataError(f"Price must be positive and volume nonnegative (CSV line {line_no}).")
                    if candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(candle.open, candle.close):
                        raise MarketDataError(f"OHLC values are inconsistent on CSV line {line_no}.")
                    rows.append(candle)
        except UnicodeDecodeError as exc:
            raise MarketDataError("CSV must be UTF-8 encoded.") from exc
        except OSError as exc:
            raise MarketDataError(f"Cannot read CSV: {exc}") from exc
        if not rows:
            raise MarketDataError("CSV contains no candle rows.")
        rows.sort(key=lambda candle: candle.timestamp)
        if len({c.timestamp for c in rows}) != len(rows):
            raise MarketDataError("CSV contains duplicate timestamps; clean the dataset before analysis.")
        return rows, str(path)


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not forward a market-data bearer token through HTTP redirects."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpJsonMarketDataProvider:
    """Provider-neutral HTTP adapter for a normalized OHLCV JSON endpoint.

    The endpoint receives market, exchange, symbol, interval, and limit query
    parameters and returns {"candles": [{timestamp, open, high, low, close, volume}]}.
    Provider-specific APIs can be wrapped by a small adapter service without
    coupling BERU's analysis code to one vendor.
    """
    name = "http_json"
    MAX_RESPONSE_BYTES = 8 * 1024 * 1024

    def __init__(self, endpoint: str, bearer_token: str = "", source_name: str = "Configured market data API", search_endpoint: str = ""):
        self.endpoint = endpoint.strip()
        self.search_endpoint = search_endpoint.strip()
        self.bearer_token = bearer_token.strip()
        self.source_name = source_name.strip() or self.name
        parsed = urlsplit(self.endpoint)
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in local_hosts):
            raise MarketDataError("Market data URL must use HTTPS (HTTP is allowed only for localhost).")
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise MarketDataError("Market data URL must be a valid endpoint without embedded credentials or fragments.")
        if self.search_endpoint:
            search_parts = urlsplit(self.search_endpoint)
            if search_parts.scheme != "https" and not (search_parts.scheme == "http" and search_parts.hostname in local_hosts):
                raise MarketDataError("Symbol-search URL must use HTTPS (HTTP is allowed only for localhost).")
            if not search_parts.hostname or search_parts.username or search_parts.password or search_parts.fragment:
                raise MarketDataError("Symbol-search URL must be valid and contain no embedded credentials or fragments.")
        self._cache = {}

    def _fetch_json(self, endpoint: str, params: dict, max_bytes: int = MAX_RESPONSE_BYTES) -> dict:
        parts = urlsplit(endpoint)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(params)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        headers = {"Accept": "application/json", "User-Agent": "BERU-Market-Analyst/1.0"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        request = Request(url, headers=headers, method="GET")
        try:
            with build_opener(_NoRedirectHandler()).open(request, timeout=15) as response:
                raw = response.read(max_bytes + 1)
        except HTTPError as exc:
            raise MarketDataError(f"Configured data endpoint returned HTTP {exc.code}; check endpoint, credentials, and market-data entitlement.") from None
        except (URLError, TimeoutError, OSError):
            raise MarketDataError("Could not reach configured market data endpoint (network or timeout).") from None
        if len(raw) > max_bytes:
            raise MarketDataError("Market data JSON response exceeds the configured size limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MarketDataError("Market data endpoint did not return valid UTF-8 JSON.") from None
        if not isinstance(payload, dict):
            raise MarketDataError("Market data endpoint must return a JSON object.")
        return payload

    def search_instruments(self, query: str, market: str = "auto") -> Sequence[dict]:
        """Resolve a company name/ticker via the configured normalized search endpoint."""
        if not self.search_endpoint:
            raise MarketDataError("Automatic company-name lookup needs BERU_MARKET_SEARCH_URL. Configure an HTTPS search endpoint returning normalized results.")
        payload = self._fetch_json(self.search_endpoint, {"query": query, "market": market, "limit": "10"}, 1024 * 1024)
        results = payload.get("results")
        if not isinstance(results, list):
            raise MarketDataError("Symbol-search endpoint must return {results:[{name,symbol,market,exchange}]}.")
        valid = []
        for row in results[:10]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()[:120]
            symbol = str(row.get("symbol", "")).strip().upper()
            venue = str(row.get("exchange", "")).strip().upper()
            market_name = str(row.get("market", "")).strip()
            try:
                normalized = _normalize_inputs(market_name, venue, symbol, "1d", "swing")
            except MarketDataError:
                continue
            valid.append({"name": name or symbol, "symbol": symbol,
                          "market": normalized[0], "exchange": normalized[1],
                          "primary": bool(row.get("primary", False))})
        return valid

    def load_candles(self, market: str, exchange: str, symbol: str,
                     interval: str) -> Tuple[Sequence[Candle], str]:
        cache_key = (market, exchange, symbol, interval)
        ttl = 60 if interval in {"1m", "5m", "15m", "30m", "1h"} else 900
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1], cached[2]

        payload = self._fetch_json(self.endpoint,
                                   {"market": market, "exchange": exchange, "symbol": symbol,
                                    "interval": interval, "limit": str(MAX_BARS)})
        rows = payload.get("candles")
        if rows is None:
            rows = payload.get("values")
        if not isinstance(rows, list) or not rows:
            message = payload.get("message") or payload.get("error") or "No candle records returned."
            raise MarketDataError(f"Market data endpoint returned no candles: {str(message)[:240]}")
        if len(rows) > MAX_BARS:
            raise MarketDataError(f"Endpoint returned more than {MAX_BARS:,} candles.")
        candles = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise MarketDataError(f"Candle record {index} is not a JSON object.")
            raw_time = row.get("timestamp", row.get("datetime", row.get("time", "")))
            try:
                candle = Candle(_parse_timestamp(str(raw_time)),
                                float(row["open"]), float(row["high"]), float(row["low"]),
                                float(row["close"]), float(row["volume"]))
            except (KeyError, TypeError, ValueError, OverflowError):
                raise MarketDataError(f"Candle record {index} has a missing or invalid field; timestamps need a UTC offset.") from None
            values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
            if not all(math.isfinite(value) for value in values):
                raise MarketDataError(f"Candle record {index} contains a non-finite value.")
            if min(candle.open, candle.high, candle.low, candle.close) <= 0 or candle.volume < 0:
                raise MarketDataError(f"Candle record {index} has invalid price or volume values.")
            if candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(candle.open, candle.close):
                raise MarketDataError(f"Candle record {index} has inconsistent OHLC values.")
            candles.append(candle)
        candles.sort(key=lambda candle: candle.timestamp)
        if len({candle.timestamp for candle in candles}) != len(candles):
            raise MarketDataError("Market data endpoint returned duplicate timestamps.")
        source = self.source_name
        result = (tuple(candles), source)
        self._cache[cache_key] = (time.monotonic(), result[0], result[1])
        return result


def _configured_provider() -> Tuple[MarketDataProvider, str]:
    selected_provider = os.getenv("BERU_MARKET_PROVIDER", "auto").strip().casefold()
    
    # NEW: explicit yahoo selection
    if selected_provider in {"yahoo", "yf"}:
        try:
            from modes.yahoo_provider import YahooMarketDataProvider
            return YahooMarketDataProvider(), ""
        except ImportError as exc:
            return CsvMarketDataProvider(), f"Yahoo provider unavailable: {exc}"
    
    twelve_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
    alpha_key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
    if selected_provider in {"twelve", "twelve_data", "twelvedata"} and not twelve_key:
        return CsvMarketDataProvider(), "BERU_MARKET_PROVIDER selects Twelve Data but TWELVE_DATA_API_KEY is missing. Using local CSV data."
    if selected_provider in {"twelve", "twelve_data", "twelvedata"} or (selected_provider == "auto" and twelve_key):
        try:
            from modes.twelve_data import TwelveDataMarketDataProvider
            return TwelveDataMarketDataProvider(twelve_key), ""
        except (ImportError, MarketDataError) as exc:
            return CsvMarketDataProvider(), f"Twelve Data configuration invalid: {type(exc).__name__}. Using local CSV data."
    if selected_provider in {"alpha", "alpha_vantage", "alphavantage"} and not alpha_key:
        return CsvMarketDataProvider(), "BERU_MARKET_PROVIDER selects Alpha Vantage but ALPHA_VANTAGE_API_KEY is missing. Using local CSV data."
    if selected_provider in {"alpha", "alpha_vantage", "alphavantage", "auto"} and alpha_key:
        try:
            from modes.alpha_vantage import AlphaVantageMarketDataProvider
            return AlphaVantageMarketDataProvider(alpha_key), ""
        except (ImportError, MarketDataError) as exc:
            return CsvMarketDataProvider(), f"Alpha Vantage configuration invalid: {type(exc).__name__}. Using local CSV data."
    endpoint = os.getenv("BERU_MARKET_DATA_URL", "").strip()
    token = os.getenv("BERU_MARKET_DATA_TOKEN", "").strip()
    source_name = os.getenv("BERU_MARKET_DATA_NAME", "Configured market data API").strip()
    search_endpoint = os.getenv("BERU_MARKET_SEARCH_URL", "").strip()
    if not endpoint:
        return CsvMarketDataProvider(), "No HTTP provider configured; using local CSV data."
    try:
        return HttpJsonMarketDataProvider(endpoint, token, source_name, search_endpoint), ""
    except MarketDataError as exc:
        return CsvMarketDataProvider(), f"Provider configuration invalid: {exc} Using local CSV data."


_provider, _provider_setup_message = _configured_provider()


def configure_market_data_provider(provider: MarketDataProvider) -> None:
    """Install a custom provider adapter in-process."""
    global _provider, _provider_setup_message
    if not callable(getattr(provider, "load_candles", None)) or not getattr(provider, "name", ""):
        raise TypeError("Provider must expose a name and load_candles(market, exchange, symbol, interval).")
    _provider = provider
    _provider_setup_message = ""


def market_data_status() -> str:
    """Explains active automatic provider or local CSV fallback."""
    if getattr(_provider, "name", "") == "twelve_data":
        mode = ("Provider: Twelve Data; daily and intraday OHLCV endpoints are enabled when covered by your account plan. "
                "BERU caches search results and candle responses briefly to reduce calls. Free-plan market coverage and streaming entitlements vary; verify the exact ticker/exchange in your dashboard. ")
    elif getattr(_provider, "name", "") == "http_json":
        mode = (f"Provider: configured HTTP/JSON API ({_provider.source_name}); BERU fetches candles automatically when analysis is requested.\n"
                "Authentication: optional bearer token loaded from BERU_MARKET_DATA_TOKEN; token is not displayed.\n"
                + ("Company-name search: configured.\n" if _provider.search_endpoint else "Company-name search: not configured; use ticker symbols or configure BERU_MARKET_SEARCH_URL.\n")
                + "Coverage, exchange delay, entitlement, and live-update frequency depend on your provider account.\n")
    elif getattr(_provider, "name", "") == "alpha_vantage":
        mode = ("Provider: Alpha Vantage direct API; daily/weekly candles and company/ticker search are enabled. "
                "Free-key quota is limited (currently 25 requests/day); this adapter does not enable intraday data. "
                "US venue is exchange-neutral; India listings use the provider's exact supported exchange suffix.")
    elif getattr(_provider, "name", "") == "local_csv":
        mode = "Provider: local CSV import only; no automatic API is configured. Add ALPHA_VANTAGE_API_KEY or TWELVE_DATA_API_KEY to .env, or configure provider-neutral URLs.\n"
    else:
        mode = f"Provider: custom adapter {_provider.name}; automatic retrieval is enabled when requested.\n"
    setup = f"{_provider_setup_message}\n" if _provider_setup_message else ""
    return ("BERU Market Analysis data status\n" + mode + setup +
            f"Data folder: {MARKET_DATA_DIR}\n"
            "HTTP candle contract: GET with market, exchange, symbol, interval, limit; JSON {candles:[{timestamp,open,high,low,close,volume}]}.\n"
            "HTTP search contract: GET with query, market, limit; JSON {results:[{name,symbol,market,exchange,primary}]}.\n"
            "CSV fallback filename: india_nse_reliance_5m.csv (market_exchange_symbol_interval.csv; market is lowercase).\n"
            "CSV columns: timestamp,open,high,low,close,volume; timestamps must include a UTC offset.\n"
            "Horizons: intraday=5m by default, swing/regular=1d, long_term=1d.\n"
            "The analyst panel includes trend, momentum, volume, volatility, historical scenarios, and a skeptical data-check agent.\n"
            "Data-source freshness and entitlement must be verified; orders are never submitted.")


def _sma(values: Sequence[float], window: int) -> Optional[float]:
    return sum(values[-window:]) / window if len(values) >= window else None


def _ema_series(values: Sequence[float], window: int) -> List[float]:
    if not values:
        return []
    alpha = 2.0 / (window + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def _rsi(values: Sequence[float], window: int = 14) -> Optional[float]:
    if len(values) <= window:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain, avg_loss = sum(gains[:window]) / window, sum(losses[:window]) / window
    for gain, loss in zip(gains[window:], losses[window:]):
        avg_gain = ((window - 1) * avg_gain + gain) / window
        avg_loss = ((window - 1) * avg_loss + loss) / window
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def _atr(candles: Sequence[Candle], window: int = 14) -> Optional[float]:
    if len(candles) <= window:
        return None
    trs = [max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
           for prev, cur in zip(candles, candles[1:])]
    value = sum(trs[:window]) / window
    for tr in trs[window:]:
        value = ((window - 1) * value + tr) / window
    return value


def _fmt(value: Optional[float], digits: int = 2) -> str:
    return "not enough data" if value is None else f"{value:,.{digits}f}"


def _age_report(last: datetime, horizon: str) -> Tuple[str, bool]:
    age = datetime.now(timezone.utc) - last.astimezone(timezone.utc)
    if age.total_seconds() < -300:
        return "timestamp is in the future", True
    age_hours = max(0.0, age.total_seconds() / 3600.0)
    # Permit analysis of the latest completed session over weekends/market holidays.
    stale = age_hours > (168 if horizon == "intraday" else 336)
    if horizon == "intraday":
        return f"{age_hours:.1f} hours old", stale
    return f"{age_hours / 24:.1f} days old", stale


def _features_at(candles: Sequence[Candle], index: int) -> Tuple[float, float, Optional[float], Optional[float]]:
    """Build lookback-only features, so historical analogs never peek forward."""
    closes = [c.close for c in candles]
    r5 = closes[index] / closes[index - 5] - 1 if index >= 5 else 0.0
    r20 = closes[index] / closes[index - 20] - 1 if index >= 20 else 0.0
    rsi = _rsi(closes[max(0, index - 15):index + 1])
    atr = _atr(candles[max(0, index - 14):index + 1])
    atr_pct = atr / closes[index] if atr is not None and closes[index] else None
    return r5, r20, rsi, atr_pct


def _historical_analogs(candles: Sequence[Candle], horizon: str, interval: str) -> str:
    """Report nearest historical indicator analogs as frequencies, never calibrated odds."""
    intraday_steps = {"1m": 60, "5m": 12, "15m": 4, "30m": 2, "1h": 1}
    steps = intraday_steps.get(interval, 1) if horizon == "intraday" else (5 if horizon == "long_term" and interval == "1d" else 1)
    current = _features_at(candles, len(candles) - 1)
    if any(value is None for value in current[2:]):
        return "Not enough lookback data to form indicator analogs."
    scale = (0.03, 0.08, 20.0, 0.02)
    candidates = []
    last_index = len(candles) - steps - 1
    for i in range(21, last_index + 1):
        if horizon == "intraday" and candles[i + steps].timestamp.date() != candles[i].timestamp.date():
            continue
        features = _features_at(candles, i)
        if any(value is None for value in features[2:]):
            continue
        distance = math.sqrt(sum(((float(a) - float(b)) / unit) ** 2
                                 for a, b, unit in zip(current, features, scale)))
        future_return = candles[i + steps].close / candles[i].close - 1.0
        gap_return = (candles[i + 1].open / candles[i].close - 1.0) if interval == "1d" and i + 1 < len(candles) else None
        candidates.append((distance, future_return, gap_return))
    candidates.sort(key=lambda item: item[0])
    sample = candidates[:min(40, len(candidates))]
    minimum = 15 if horizon == "intraday" else 20
    period = (f"next ~60 minutes ({steps} same-session bars)" if horizon == "intraday" else ("next 5 daily bars" if steps == 5 else "next candle"))
    if len(sample) < minimum:
        return f"Historical analogs unavailable: only {len(sample)} comparable outcomes; need {minimum}."
    atr_pct = float(current[3])
    neutral_band = max(0.001, atr_pct * math.sqrt(steps) * 0.25)
    ups = sum(1 for _, ret, _ in sample if ret > neutral_band)
    downs = sum(1 for _, ret, _ in sample if ret < -neutral_band)
    flats = len(sample) - ups - downs
    returns = [ret for _, ret, _ in sample]
    result = (f"Historical analogs ({len(sample)} nearest; {period}; neutral band ±{neutral_band * 100:.2f}%): "
              f"up {ups / len(sample):.0%}, roughly flat {flats / len(sample):.0%}, down {downs / len(sample):.0%}; "
              f"median analog return {median(returns) * 100:+.2f}%. These are uncalibrated historical sample frequencies, not predicted probabilities.")
    gaps = [gap for _, _, gap in sample if gap is not None]
    if gaps:
        result += (f" Historical opening gaps in the same analog set: median {median(gaps) * 100:+.2f}%; "
                   f"positive {sum(g > 0 for g in gaps) / len(gaps):.0%}, negative {sum(g < 0 for g in gaps) / len(gaps):.0%}.")
    return result


def _specialist_panel(candles: Sequence[Candle], horizon: str, interval: str,
                      closes: Sequence[float], volumes: Sequence[float], last: Candle,
                      sma20: Optional[float], sma50: Optional[float], sma200: Optional[float],
                      rsi: Optional[float], atr: Optional[float]) -> List[str]:
    """Five focused analysis agents plus a skeptic; all findings are deterministic and auditable."""
    lines = ["", "MULTI-AGENT REVIEW"]
    trend_vote = 0
    if sma20 is not None and sma50 is not None:
        if last.close > sma20 > sma50:
            trend_text, trend_vote = "uptrend structure (close > SMA20 > SMA50)", 1
        elif last.close < sma20 < sma50:
            trend_text, trend_vote = "downtrend structure (close < SMA20 < SMA50)", -1
        else:
            trend_text = "mixed moving-average structure"
    else:
        trend_text = "insufficient history for SMA20/SMA50 comparison"
    lines.append(f"- Trend agent: {trend_text}.")

    momentum_vote = 0
    closes_ema = _ema_series(closes, 12)
    long_ema = _ema_series(closes, 26)
    macd_series = [a - b for a, b in zip(closes_ema, long_ema)]
    signal_series = _ema_series(macd_series, 9)
    macd_value = macd_series[-1] if macd_series else 0.0
    signal_value = signal_series[-1] if signal_series else 0.0
    if rsi is not None and macd_value > signal_value and rsi >= 50:
        momentum_vote = 1
    elif rsi is not None and macd_value < signal_value and rsi < 50:
        momentum_vote = -1
    momentum_text = f"RSI { _fmt(rsi) }; MACD is {'above' if macd_value > signal_value else 'below/equal to'} its signal line"
    lines.append(f"- Momentum agent: {momentum_text}; {('positive' if momentum_vote > 0 else 'negative' if momentum_vote < 0 else 'mixed')} evidence.")

    if horizon == "intraday":
        same_day = [c for c in candles if c.timestamp.date() == last.timestamp.date()]
        total = sum(c.volume for c in same_day)
        vwap = sum(((c.high + c.low + c.close) / 3) * c.volume for c in same_day) / total if total else None
        participation_text = f"session VWAP {_fmt(vwap)}; current close {'above' if vwap is not None and last.close >= vwap else 'below/unavailable versus'} VWAP. Volume does not reveal buyer identities or order-flow direction"
    elif len(volumes) >= 21:
        baseline = sum(volumes[-21:-1]) / 20
        participation_text = f"latest volume is {last.volume / baseline:.2f}x its previous-20-bar mean" if baseline else "relative volume unavailable (zero baseline)"
    else:
        participation_text = "insufficient baseline for relative volume"
    lines.append(f"- Volume/participation agent: {participation_text}.")

    atr_pct = (atr / last.close * 100) if atr is not None and last.close else None
    lines.append(f"- Volatility/risk agent: ATR14 is {_fmt(atr)} ({_fmt(atr_pct)}% of close); this describes recent range, not a safe stop or maximum loss.")

    analog_report = _historical_analogs(candles, horizon, interval)
    lines.append(f"- Historical-scenario agent: {analog_report}")

    if trend_vote and momentum_vote and trend_vote != momentum_vote:
        skeptic = "trend and momentum agents disagree; reduce confidence in a single directional narrative"
    elif not trend_vote or not momentum_vote:
        skeptic = "at least one directional agent is inconclusive; mixed evidence should remain mixed"
    else:
        skeptic = "trend and momentum agree, but agreement does not establish predictive edge"
    lines.append(f"- Skeptic/data-check agent: {skeptic}; feed timestamps and source provenance still require user verification.")

    bullish_votes = int(trend_vote > 0) + int(momentum_vote > 0)
    bearish_votes = int(trend_vote < 0) + int(momentum_vote < 0)
    setup = "constructive technical evidence" if bullish_votes == 2 else "weak technical evidence" if bearish_votes == 2 else "mixed / wait-for-confirmation evidence"
    lines.append(f"- Technical setup summary: {setup} ({bullish_votes} bullish and {bearish_votes} bearish directional votes). This is not a personalized instruction to buy or sell.")
    return lines


def _analyze(candles: Sequence[Candle], market: str, exchange: str, symbol: str,
             interval: str, horizon: str, source: str,
             is_historical: bool = False) -> str:
    min_bars = MINIMUM_BARS[horizon]
    if len(candles) < min_bars:
        return f"Not enough history for {horizon}: received {len(candles)} bars; need {min_bars}. No conclusion generated."
    last = candles[-1]
    age_text, stale = _age_report(last.timestamp, horizon)
    if stale and not is_historical:
        return f"DATA TOO OLD for a current {horizon} read. Last candle: {last.timestamp.isoformat()} ({age_text}). Load fresh data."
    if stale and is_historical:
        # Historical queries are allowed to be stale — that's the whole point.
        pass
    closes, volumes = [c.close for c in candles], [c.volume for c in candles]
    lines = [f"=== STOCK DATA ANALYSIS: {market.upper()} {exchange}:{symbol} ===",
             f"Mode: {horizon} | Interval: {interval} | Bars: {len(candles)}",
             f"Source: {source} (provider data; accuracy/licensing is not independently audited)",
             f"Latest candle: {last.timestamp.isoformat()} ({age_text})",
             f"Open {_fmt(last.open)} | High {_fmt(last.high)} | Low {_fmt(last.low)} | Close {_fmt(last.close)} | Volume {last.volume:,.0f}",
             "", "TECHNICAL EVIDENCE AND HISTORICAL SCENARIOS (not guaranteed forecasts):"]
    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    lines.append(f"- SMA 20/50/200: {_fmt(sma20)} / {_fmt(sma50)} / {_fmt(sma200)}")
    rsi = _rsi(closes)
    rsi_note = " (high momentum; not a sell signal by itself)" if rsi is not None and rsi >= 70 else " (low momentum; not a buy signal by itself)" if rsi is not None and rsi <= 30 else ""
    lines.append(f"- RSI 14: {_fmt(rsi)}{rsi_note}")
    if len(closes) >= 35:
        macd = [a - b for a, b in zip(_ema_series(closes, 12), _ema_series(closes, 26))]
        signal = _ema_series(macd, 9)
        lines.append(f"- MACD 12/26/9: line {_fmt(macd[-1])}, signal {_fmt(signal[-1])}, histogram {_fmt(macd[-1] - signal[-1])}")
    else:
        lines.append("- MACD 12/26/9: not enough bars (need 35).")
    atr = _atr(candles)
    lines.append(f"- ATR 14: {_fmt(atr)} (historical range measure, not a guaranteed stop distance)")
    if horizon != "intraday" and len(volumes) >= 21:
        baseline = sum(volumes[-21:-1]) / 20
        lines.append(f"- Latest volume vs previous 20 bars: {last.volume / baseline:.2f}x" if baseline else "- Relative volume unavailable (zero baseline).")
    if horizon == "intraday":
        session_date = last.timestamp.date()
        session = [c for c in candles if c.timestamp.date() == session_date]
        total_volume = sum(c.volume for c in session)
        vwap = sum(((c.high + c.low + c.close) / 3) * c.volume for c in session) / total_volume if total_volume else None
        lines.append(f"- Session VWAP from supplied bars: {_fmt(vwap)}")
    if sma20 is not None and sma50 is not None:
        if last.close > sma20 > sma50:
            trend = "close > SMA20 > SMA50; positive trend structure in this sample"
        elif last.close < sma20 < sma50:
            trend = "close < SMA20 < SMA50; negative trend structure in this sample"
        else:
            trend = "price and averages are mixed; simple trend rule is inconclusive"
        lines.append(f"- Trend context: {trend}.")
    window = candles[-20:]
    lines.append(f"- 20-bar range: {_fmt(min(c.low for c in window))} to {_fmt(max(c.high for c in window))}; not validated support/resistance.")
    if len(closes) >= 6:
        change = (closes[-1] / closes[-6] - 1) * 100
        lines.append(f"- Change over last 5 bars: {change:+.2f}% (bar count, not calendar days).")
    lines.extend(_specialist_panel(candles, horizon, interval, closes, volumes, last, sma20, sma50, sma200, rsi, atr))
    lines += ["", "LIMITS:",
              "- Volume is the reported number of shares/contracts, not the number of distinct people buying or selling.",
              "- OHLCV candles do not contain verified buyer/seller order-flow split or trader identities.",
              "- Historical analog frequencies are not calibrated probabilities; no guaranteed forecast or personal suitability assessment is provided.",
              "- The technical setup label is educational evidence, not a personalized buy/sell instruction, price target, or order execution.",
              "- Long-term analysis needs fundamentals, valuation, and corporate-action-adjusted data; they are not included here.",
              "- Daily-bar analogs can summarize opening gaps and next-session close-to-close moves, but cannot reliably predict tomorrow's open. Intraday scenarios depend on same-session 5-minute/other supplied candles.",
              "- Treat this as descriptive evidence. Any strategy needs transaction-cost-aware, out-of-sample validation."]
    return "\n".join(lines)


def analyze_stock_by_name(stock_name: str, market: str = "auto", as_of: str = "") -> str:
    """Resolve a company name to a supported listing, then fetch and analyze daily + intraday candles."""
    query = (stock_name or "").strip()
    try:
        _parse_cutoff(as_of)
    except MarketDataError as exc:
        return f"Stock lookup unavailable: {exc}"
    if not query or len(query) > 120:
        return "Enter a company name or ticker (1-120 characters)."
    searcher = getattr(_provider, "search_instruments", None)
    if not callable(searcher):
        return ("Automatic company-name lookup is not configured. Set BERU_MARKET_SEARCH_URL and BERU_MARKET_DATA_URL "
                "in .env, or use the existing ticker-based tool/local CSV workflow.")
    market_aliases = {"india": "india", "in": "india", "nse": "india", "bse": "india",
                      "us": "us", "usa": "us", "united states": "us", "auto": "auto"}
    market_filter = market_aliases.get((market or "auto").strip().lower())
    if not market_filter:
        return "Market filter must be auto, India, or US."
    try:
        candidates = list(searcher(query, market_filter))
    except MarketDataError as exc:
        return f"Stock lookup unavailable: {exc}"
    if market_filter != "auto":
        candidates = [item for item in candidates if item["market"] == market_filter]
    if not candidates:
        return f"No supported India/US listing found for '{query}'. Check spelling or configure provider coverage."
    exact = [item for item in candidates if query.casefold() in {item["name"].casefold(), item["symbol"].casefold()}]
    preferred = exact if exact else candidates
    primaries = [item for item in preferred if item.get("primary")]
    if len(primaries) == 1:
        selected = primaries[0]
    elif len(preferred) == 1:
        selected = preferred[0]
    else:
        options = "; ".join(f"{item['name']} ({item['market'].upper()} {item['exchange']}:{item['symbol']})" for item in preferred[:5])
        return f"'{query}' matches multiple listings. Please choose one: {options}."

    market_label = "India" if selected["market"] == "india" else "US"
    symbol, exchange = selected["symbol"], selected["exchange"]
    sections = [f"=== AUTOMATIC STOCK LOOKUP ===\nSelected: {selected['name']} | {market_label} {exchange}:{symbol}\nSource: {_provider.name}\n"]
    # Daily candles support the prior-session/next-session view, including historical opening-gap samples.
    daily = analyze_stock_market(symbol, market_label, exchange, "swing", "1d", as_of=as_of)
    sections.append("NEXT SESSION / LAST DAILY CANDLES\n" + daily)
    # Historical cutoff runs must never append a newer intraday view.
    if as_of.strip():
        sections.append("INTRADAY DATA\nSkipped because an as-of cutoff was requested; only candles through that date are used.")
    # Intraday is refreshed on demand; if the provider does not license this interval, preserve the daily result.
    elif getattr(_provider, "name", "") == "alpha_vantage":
        sections.append("INTRADAY DATA\nNot enabled for this Alpha Vantage setup; use the daily historical analysis.")
    else:
        intraday = analyze_stock_market(symbol, market_label, exchange, "intraday", "5m")
        sections.append("INTRADAY / NEXT APPROXIMATE HOUR\n" + intraday)
    sections.append("\nData is fetched on this request (subject to the configured provider's entitlement and cache). No exact or guaranteed prediction is possible.")
    return "\n\n".join(sections)


def _parse_cutoff(as_of: str) -> Optional[date]:
    if not (as_of or "").strip():
        return None
    try:
        return date.fromisoformat(as_of.strip())
    except ValueError:
        raise MarketDataError("as_of must be an ISO date in YYYY-MM-DD format.") from None



def _try_resolve_symbol(symbol: str, market: str, exchange: str) -> Optional[dict]:
    """If a symbol looks human-written (e.g. 'Infosys'), try provider symbol search
    to find the canonical listing. Returns {symbol, exchange, market, name} or None."""
    searcher = getattr(_provider, "search_instruments", None)
    if not callable(searcher):
        return None
    try:
        results = list(searcher(symbol, "auto"))
    except MarketDataError:
        return None
    if not results:
        return None
    # Prefer exact match on name or symbol, then single result
    query = symbol.casefold().strip()
    exact = [r for r in results
             if query == str(r.get("name", "")).casefold()
             or query == str(r.get("symbol", "")).casefold()]
    pick = (exact or results)[0]
    if len(exact) == 1 or len(results) == 1:
        return pick
    return None  # ambiguous — let the caller report options


def analyze_stock_market(symbol: str, market: str = "India", exchange: str = "",
                         horizon: str = "swing", interval: str = "", as_of: str = "") -> str:
    try:
        cutoff = _parse_cutoff(as_of)
        market_key, exchange_key, symbol_key, interval_key, horizon_key = _normalize_inputs(
            market, exchange, symbol, interval, horizon)

        # FIRST ATTEMPT: treat input as an exact provider symbol.
        candles, source = None, None
        try:
            candles, source = _provider.load_candles(market_key, exchange_key, symbol_key, interval_key)
        except MarketDataError:
            pass  # fall through to resolution

        # FALLBACK: resolve human-readable name → canonical symbol.
        if not candles:
            resolved = _try_resolve_symbol(symbol, market_key, exchange_key)
            if resolved:
                # Re-run normalization with the resolved canonical symbol
                market_key = resolved.get("market", market_key)
                exchange_key = resolved.get("exchange", exchange_key)
                symbol_key = resolved.get("symbol", symbol_key)
                candles, source = _provider.load_candles(
                    market_key, exchange_key, symbol_key, interval_key)
                source += f" (resolved from '{symbol}')"
            else:
                # No resolution — give the user actionable guidance, not a silent failure.
                raise MarketDataError(
                    f"Could not resolve '{symbol}' to a listing on {market}. "
                    f"Try the exact ticker (e.g. 'TCS', 'INFY', 'RELIANCE') or "
                    f"set exchange='BSE' or 'NSE' explicitly."
                )

        if cutoff is not None:
            candles = [c for c in candles if c.timestamp.date() <= cutoff]
            source += f" (cut off {cutoff.isoformat()})"
            if not candles:
                raise MarketDataError(f"No candles exist on or before {cutoff.isoformat()}.")

        return _analyze(candles, market_key, exchange_key, symbol_key, interval_key,
                        horizon_key, source, is_historical=(cutoff is not None))
    except MarketDataError as exc:
        return f"Market analysis unavailable: {exc}"
    except Exception as exc:
        return f"Market analysis failed safely: {type(exc).__name__}: {exc}"

def classify_stock_setup(symbol: str, market: str = "India", exchange: str = "",
                         as_of: str = "") -> str:
    """Return a single technical label (no refusal, no hedging).
    Uses the same indicators as analyze_stock_market but outputs one verdict."""
    try:
        cutoff = _parse_cutoff(as_of)
        market_key, exchange_key, symbol_key, interval_key, horizon_key = _normalize_inputs(
            market, exchange, symbol, "1d", "swing")
        candles, source = _provider.load_candles(
            market_key, exchange_key, symbol_key, "1d")
        if cutoff is not None:
            filtered = [c for c in candles if c.timestamp.date() <= cutoff]
            if not filtered:
                raise MarketDataError(
                    f"No candles exist on or before {cutoff.isoformat()}. "
                    f"Latest available: {candles[-1].timestamp.date().isoformat()}."
                )
            # Refuse silent substitution: if the requested date has no bar, say so.
            if filtered[-1].timestamp.date() != cutoff:
                raise MarketDataError(
                    f"Requested {cutoff.isoformat()}, but the latest bar on or before it is "
                    f"{filtered[-1].timestamp.date().isoformat()} "
                    f"(weekend, holiday, or data not yet updated). "
                    f"Use a valid trading date, or run after market close."
                )
            candles = filtered
        if len(candles) < 60:
            raise MarketDataError(f"Need 60 bars, got {len(candles)}.")

        closes = [c.close for c in candles]
        last = candles[-1]
        sma20 = _sma(closes, 20)
        sma50 = _sma(closes, 50)
        rsi = _rsi(closes)
        ema12 = _ema_series(closes, 12)
        ema26 = _ema_series(closes, 26)
        macd_line = [a - b for a, b in zip(ema12, ema26)]
        macd_sig = _ema_series(macd_line, 9)
        macd = macd_line[-1]
        signal = macd_sig[-1]

        score = 0
        reasons = []
        
        # Safely handle missing data (prevents the 'nan' bug)
        if sma20 is None or sma50 is None or macd is None or signal is None:
            return (
                f"LABEL: NEUTRAL (DATA MISSING)\n"
                f"Symbol: {market_key.upper()} {exchange_key}:{symbol_key}\n"
                f"As of: {last.timestamp.isoformat()}\n"
                f"Score: 0\n"
                f"Reasons:\n  - Could not load enough daily historical data to calculate SMA/MACD.\n"
                f"  - This is likely a temporary API glitch with the data provider.\n"
                f"\nThis is a technical classification of current indicators, not a prediction."
            )

        if last.close > sma20:
            score += 1; reasons.append(f"close {last.close:.2f} > SMA20 {sma20:.2f}")
        else:
            score -= 1; reasons.append(f"close {last.close:.2f} < SMA20 {sma20:.2f}")
            
        if last.close > sma50:
            score += 1; reasons.append(f"close {last.close:.2f} > SMA50 {sma50:.2f}")
        else:
            score -= 1; reasons.append(f"close {last.close:.2f} < SMA50 {sma50:.2f}")
            
        if macd > signal:
            score += 1; reasons.append(f"MACD {macd:.2f} > signal {signal:.2f}")
        else:
            score -= 1; reasons.append(f"MACD {macd:.2f} <= signal {signal:.2f}")
            
        if rsi is not None and rsi > 70:
            score -= 1; reasons.append(f"RSI {rsi:.2f} overbought (>70) — caution")
        elif rsi is not None and rsi < 30:
            score += 1; reasons.append(f"RSI {rsi:.2f} oversold (<30) — bounce potential")

        if score >= 2:   label = "BULLISH"
        elif score == 1: label = "MILDLY_BULLISH"
        elif score == 0: label = "NEUTRAL"
        elif score == -1: label = "MILDLY_BEARISH"
        else:            label = "BEARISH"

        return (
            f"LABEL: {label}\n"
            f"Symbol: {market_key.upper()} {exchange_key}:{symbol_key}\n"
            f"As of: {last.timestamp.isoformat()}\n"
            f"Score: {score:+d} (bullish {sum(1 for r in reasons if '>' in r and 'overbought' not in r)} / "
            f"caution {sum(1 for r in reasons if 'overbought' in r or 'oversold' in r)})\n"
            f"Reasons:\n  - " + "\n  - ".join(reasons) + "\n"
            f"\nThis is a technical classification of current indicators, not a prediction."
        )
    except MarketDataError as exc:
        return f"Market analysis unavailable: {exc}"


def analyze_intraday_momentum(symbol: str, market: str = "India",
                              exchange: str = "NSE", as_of: str = "",
                              target_time: str = "") -> str:
    """Quantify last 15m/30m/60m behavior + short-term pressure.
    as_of: optional YYYY-MM-DD to analyze a specific historical date.
    target_time: optional HH:MM (e.g. '10:05') — cutoff at that intraday moment.
    Descriptive only. Not a prediction."""
    try:
        market_key, exchange_key, symbol_key, _, _ = _normalize_inputs(
            market, exchange, symbol, "5m", "intraday")
        candles, source = _provider.load_candles(market_key, exchange_key, symbol_key, "5m")
    except MarketDataError as exc:
        return f"Intraday analysis unavailable: {exc}"

    all_candles = candles  # preserve for error messages

    # Historical filtering
    if as_of:
        try:
            cutoff_date = _parse_cutoff(as_of)
        except MarketDataError as exc:
            return f"Intraday analysis unavailable: {exc}"
        candles = [c for c in candles if c.timestamp.date() == cutoff_date]
        if not candles:
            available = sorted(set(c.timestamp.date().isoformat() for c in all_candles))[-5:]
            return (f"Intraday analysis unavailable: no 5-minute bars for {as_of}. "
                    f"Recent available dates: {', '.join(available)}.")

        # Optionally stop at a specific intraday time (e.g., '10:05')
        if target_time:
            try:
                hh, mm = target_time.split(":")
                cutoff_dt = candles[0].timestamp.replace(hour=int(hh), minute=int(mm), second=0)
                candles = [c for c in candles if c.timestamp <= cutoff_dt]
                if len(candles) < 4:
                    return (f"Not enough bars before {target_time} on {as_of} "
                            f"(got {len(candles)}, need ≥4).")
            except (ValueError, AttributeError):
                return f"Invalid target_time '{target_time}'. Use HH:MM (e.g., '10:05')."

    # Minimum-bar check must run on the FULL day's candles, not the filtered subset.
    # For live monitoring, require 20+ bars. For historical target_time, require only 4.
    min_required = 20 if not (as_of and target_time) else 4
    if len(candles) < min_required:
        return (f"Need ≥{min_required} 5-minute bars, got {len(candles)}. "
                f"Market may have just opened, or target_time is too early.")

    last = candles[-1]
    now = last.timestamp
    same_day = [c for c in candles if c.timestamp.date() == now.date()]
    if len(same_day) < 4:
        return "Not enough bars from today yet. Try again after 09:30 IST."

    def _ret(bars_back: int) -> Optional[float]:
        if len(candles) > bars_back:
            return (last.close / candles[-1 - bars_back].close - 1) * 100
        return None

    r15 = _ret(3)     # 3 × 5m = 15 min
    r30 = _ret(6)     # 30 min
    r60 = _ret(12)    # 60 min
    r120 = _ret(24)   # 120 min (may be None early in session)

    # Intraday VWAP from today's bars
    total_v = sum(c.volume for c in same_day)
    vwap = (sum(((c.high + c.low + c.close) / 3) * c.volume for c in same_day) / total_v
            if total_v else None)

    # Short-term RSI on 5m closes (7-period)
    closes = [c.close for c in candles]
    rsi7 = _rsi(closes[-8:], window=7) if len(closes) >= 8 else None

    # Buy/sell pressure proxy: close position within last candle's range, × volume
    rng = last.high - last.low
    close_pos = ((last.close - last.low) / rng) if rng > 0 else 0.5
    recent_vol = sum(c.volume for c in candles[-3:])
    baseline_vol = sum(c.volume for c in candles[-23:-3]) / 20 if len(candles) >= 23 else recent_vol
    vol_ratio = (recent_vol / 3) / baseline_vol if baseline_vol else 1.0

    # 5-point label based on VWAP + RSI + pressure + volume
    score = 0
    reasons = []
    if vwap and last.close > vwap:
        score += 1; reasons.append(f"price {last.close:.2f} > VWAP {vwap:.2f}")
    elif vwap:
        score -= 1; reasons.append(f"price {last.close:.2f} < VWAP {vwap:.2f}")
    if rsi7 is not None:
        if rsi7 > 65:
            score -= 1; reasons.append(f"RSI7 {rsi7:.1f} overbought")
        elif rsi7 < 35:
            score += 1; reasons.append(f"RSI7 {rsi7:.1f} oversold")
        else:
            reasons.append(f"RSI7 {rsi7:.1f} neutral")
    if close_pos > 0.6:
        score += 1; reasons.append(f"last candle closed in top {close_pos*100:.0f}% of range")
    elif close_pos < 0.4:
        score -= 1; reasons.append(f"last candle closed in bottom {close_pos*100:.0f}% of range")
    if vol_ratio > 1.5:
        reasons.append(f"volume {vol_ratio:.1f}× baseline (elevated)")
    elif vol_ratio < 0.6:
        reasons.append(f"volume {vol_ratio:.1f}× baseline (thin)")

    if score >= 2:   label = "BULLISH_NEXT_30_60MIN"
    elif score == 1: label = "MILDLY_BULLISH"
    elif score == 0: label = "NEUTRAL"
    elif score == -1: label = "MILDLY_BEARISH"
    else:            label = "BEARISH_NEXT_30_60MIN"

    fmt = lambda v: f"{v:+.2f}%" if v is not None else "n/a"
    lines = [
        f"=== INTRADAY MOMENTUM: {market_key.upper()} {exchange_key}:{symbol_key} ===",
        f"Latest bar: {last.timestamp.isoformat()} | Close {last.close:.2f} | Volume {last.volume:,.0f}",
        f"Return last 15m: {fmt(r15)} | 30m: {fmt(r30)} | 60m: {fmt(r60)} | 120m: {fmt(r120)}",
        f"VWAP (today): {vwap:.2f}" if vwap else "VWAP: n/a",
        f"RSI7 (5m): {rsi7:.1f}" if rsi7 else "RSI7: n/a",
        f"Candle close position: {close_pos*100:.0f}% of range | Volume ratio: {vol_ratio:.2f}×",
        f"\nLABEL: {label}\nScore: {score:+d}",
        "Reasons:\n  - " + "\n  - ".join(reasons),
        "\nThis is a description of recent behavior, not a prediction.",
    ]
    return "\n".join(lines)

def analyze_30m_swing_momentum(symbol: str, market: str = "India",
                               exchange: str = "NSE", as_of: str = "",
                               target_time: str = "") -> str:
    """Quantify 30-minute swing behavior. Uses 30m candles to filter out 5m noise.
    as_of: optional YYYY-MM-DD. target_time: optional HH:MM cutoff.
    Descriptive only. Not a prediction."""
    try:
        market_key, exchange_key, symbol_key, _, _ = _normalize_inputs(
            market, exchange, symbol, "30m", "intraday")
        candles, source = _provider.load_candles(market_key, exchange_key, symbol_key, "30m")
    except MarketDataError as exc:
        return f"Swing analysis unavailable: {exc}"

    all_candles = candles

    if as_of:
        try:
            cutoff_date = _parse_cutoff(as_of)
        except MarketDataError as exc:
            return f"Swing analysis unavailable: {exc}"
        
        candles = [c for c in candles if c.timestamp.date() == cutoff_date]
        if not candles:
            available = sorted(set(c.timestamp.date().isoformat() for c in all_candles))[-5:]
            return (f"Swing analysis unavailable: no 30-minute bars for {as_of}. "
                    f"Recent available dates: {', '.join(available)}.")

        if target_time:
            try:
                hh, mm = target_time.split(":")
                cutoff_dt = candles[0].timestamp.replace(hour=int(hh), minute=int(mm), second=0)
                candles = [c for c in candles if c.timestamp <= cutoff_dt]
                if len(candles) < 2:
                    return (f"Not enough bars before {target_time} on {as_of} "
                            f"(got {len(candles)}, need ≥2).")
            except (ValueError, AttributeError):
                return f"Invalid target_time '{target_time}'. Use HH:MM."

    # Need at least 4 bars (2 hours) to calculate a reliable short-term trend
    min_required = 4 if (as_of and target_time) else 15
    if len(candles) < min_required:
        return (f"Need ≥{min_required} 30-minute bars, got {len(candles)}. "
                f"Market may have just opened, or target_time is too early.")

    last = candles[-1]
    closes = [c.close for c in candles]
    
    # Returns based on 30m intervals
    # 1 bar = 30m, 2 bars = 60m, 4 bars = 120m
    def _ret(bars_back: int) -> Optional[float]:
        if len(candles) > bars_back:
            return (last.close / candles[-1 - bars_back].close - 1) * 100
        return None

    r30 = _ret(1)
    r60 = _ret(2)
    r120 = _ret(4)

    # RSI on 30m closes
    rsi14 = _rsi(closes[-15:], window=14) if len(closes) >= 15 else None

    # 30m moving average (SMA 5 = 2.5 hours of trend)
    sma5 = _sma(closes, 5)

    # Candle structure
    rng = last.high - last.low
    close_pos = ((last.close - last.low) / rng) if rng > 0 else 0.5
    
    # Volume
    recent_vol = sum(c.volume for c in candles[-2:])
    baseline_vol = sum(c.volume for c in candles[-12:-2]) / 10 if len(candles) >= 12 else recent_vol
    vol_ratio = (recent_vol / 2) / baseline_vol if baseline_vol else 1.0

    # Scoring Logic
    score = 0
    reasons = []
    
    if sma5 and last.close > sma5:
        score += 1; reasons.append(f"close {last.close:.2f} > SMA5 (30m) {sma5:.2f}")
    elif sma5:
        score -= 1; reasons.append(f"close {last.close:.2f} < SMA5 (30m) {sma5:.2f}")

    if rsi14 is not None:
        if rsi14 > 70:
            score -= 1; reasons.append(f"RSI14 {rsi14:.1f} overbought")
        elif rsi14 < 30:
            score += 1; reasons.append(f"RSI14 {rsi14:.1f} oversold")
        else:
            reasons.append(f"RSI14 {rsi14:.1f} neutral")

    if close_pos > 0.6:
        score += 1; reasons.append(f"last 30m candle closed in top {close_pos*100:.0f}% of range")
    elif close_pos < 0.4:
        score -= 1; reasons.append(f"last 30m candle closed in bottom {close_pos*100:.0f}% of range")

    if vol_ratio > 1.5:
        reasons.append(f"volume {vol_ratio:.1f}× baseline (elevated)")
    elif vol_ratio < 0.6:
        reasons.append(f"volume {vol_ratio:.1f}× baseline (thin)")

    if score >= 2:   label = "STRONG_BULLISH_SWING"
    elif score == 1: label = "MILDLY_BULLISH"
    elif score == 0: label = "NEUTRAL"
    elif score == -1: label = "MILDLY_BEARISH"
    else:            label = "STRONG_BEARISH_SWING"

    fmt = lambda v: f"{v:+.2f}%" if v is not None else "n/a"
    lines = [
        f"=== 30M SWING MOMENTUM: {market_key.upper()} {exchange_key}:{symbol_key} ===",
        f"Latest bar: {last.timestamp.isoformat()} | Close {last.close:.2f} | Volume {last.volume:,.0f}",
        f"Return last 30m: {fmt(r30)} | 60m: {fmt(r60)} | 120m: {fmt(r120)}",
        f"SMA 5 (30m): {sma5:.2f}" if sma5 else "SMA 5 (30m): n/a",
        f"RSI14 (30m): {rsi14:.1f}" if rsi14 else "RSI14: n/a",
        f"Candle close position: {close_pos*100:.0f}% of range | Volume ratio: {vol_ratio:.2f}×",
        f"\nLABEL: {label}\nScore: {score:+d}",
        "Reasons:\n  - " + "\n  - ".join(reasons),
        "\nThis is a description of recent 30m behavior, not a prediction.",
    ]
    return "\n".join(lines)

def synthesize_market_verdict(symbol: str, market: str = "India", exchange: str = "NSE", 
                              as_of: str = "", target_time: str = "") -> str:
    """Combines 5m, 30m, and Daily analysis into a single human-readable verdict."""
    
    m5_raw = analyze_intraday_momentum(symbol, market, exchange, as_of, target_time)
    m30_raw = analyze_30m_swing_momentum(symbol, market, exchange, as_of, target_time)
    daily_raw = classify_stock_setup(symbol, market, exchange, as_of)
    
    if "unavailable" in m5_raw or "unavailable" in m30_raw or "unavailable" in daily_raw:
        return f"VERDICT: DATA UNAVAILABLE\nReason:\n{m5_raw[:100]}"

    import re
    def get_score(text):
        match = re.search(r"Score:\s*([+-]?\d+)", text)
        return int(match.group(1)) if match else 0

    s5 = get_score(m5_raw)
    s30 = get_score(m30_raw)
    sdaily = get_score(daily_raw)

    conclusion = "NEUTRAL / MIXED"
    action = "Stay out. No clear edge right now."

    # Logic 1: Long Term Bullish, Short Term Bearish (The Pullback)
    if sdaily > 0 and (s30 < 0 or s5 < 0):
        conclusion = "INTRADAY DOWNTREND / MACRO UPTREND (Healthy Pullback)"
        action = ("Today is weak for intraday (do not buy calls). However, the overall trend is UP. "
                  "Wait for the 5-min to hit oversold (RSI < 30) and turn green before buying the dip.")

    # Logic 2: Long Term Bearish, Short Term Bullish (The Bull Trap)
    elif sdaily < 0 and (s30 > 0 or s5 > 0):
        conclusion = "INTRADAY BOUNCE / MACRO DOWNTREND (Bull Trap)"
        action = ("Today shows short-term buying, but the long-term trend is broken. Do not hold overnight. "
                  "This is likely a fake-out. Short the rallies.")

    # Logic 3: Everything is Bearish OR Flat (The Crash)
    elif sdaily < 0 and s30 <= 0 and s5 <= 0:
        conclusion = "STRONG BEARISH ALIGNMENT (Cascading Down)"
        action = "High probability of a continued drop. Look for short entries."

    # Logic 4: Everything is Bullish OR Flat (The Breakout)
    elif sdaily > 0 and s30 >= 0 and s5 >= 0:
        conclusion = "STRONG BULLISH ALIGNMENT (Clear Skies)"
        action = "High probability of a continued rise. Look for long entries."

    # Logic 5: Short term is fighting itself
    elif (s5 > 0 and s30 < 0) or (s5 < 0 and s30 > 0):
        conclusion = "CONFLICTED INTRADAY (Choppy/Noisy)"
        action = "5-min and 30-min disagree. This is a trap. Wait for them to align."

    # Logic 6: Completely neutral
    elif s5 == 0 and s30 == 0:
        conclusion = "DEAD NEUTRAL"
        action = "No volume, no momentum. Protect your capital and wait."

    # The Final Combined Output
    return (
        f"==================================================\n"
        f"🌟 EXECUTIVE VERDICT: {symbol}\n"
        f"==================================================\n"
        f"Scores -> 5-Min: {s5} | 30-Min: {s30} | Daily: {sdaily}\n\n"
        f"VERDICT: {conclusion}\n"
        f"ACTION: {action}\n\n"
        f"==================================================\n"
        f"🔍 DETAILED EVIDENCE\n"
        f"==================================================\n\n"
        f"--- [1] 5-MINUTE MOMENTUM ---\n{m5_raw}\n\n"
        f"--- [2] 30-MINUTE SWING ---\n{m30_raw}\n\n"
        f"--- [3] DAILY SETUP ---\n{daily_raw}"
    )