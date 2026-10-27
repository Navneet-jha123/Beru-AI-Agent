"""Transparent multi-symbol stock screening using BERU's configured candle provider."""
from __future__ import annotations

from collections.abc import Sequence

from modes import market_analyst as core


def screen_stock_watchlist(symbols: Sequence[str], market: str = "India",
                           exchange: str = "", interval: str = "1d") -> str:
    """Compare up to 20 symbols using visible technical conditions, not advice."""
    if isinstance(symbols, str):
        symbols = [part.strip() for part in symbols.split(",")]
    if not isinstance(symbols, Sequence):
        return "Provide a list of 1-20 ticker symbols."
    symbols = list(dict.fromkeys(str(item).strip().upper() for item in symbols if str(item).strip()))
    if not symbols or len(symbols) > 20:
        return "Provide between 1 and 20 unique ticker symbols."
    try:
        market_key, exchange_key, _, interval_key, horizon = core._normalize_inputs(
            market, exchange, symbols[0], interval, "swing")
    except core.MarketDataError as exc:
        return f"Watchlist setup error: {exc}"

    rows, failures = [], []
    for symbol in symbols:
        try:
            _, _, symbol_key, _, _ = core._normalize_inputs(
                market_key, exchange_key, symbol, interval_key, horizon)
            candles, source = core._provider.load_candles(
                market_key, exchange_key, symbol_key, interval_key)
            if len(candles) < core.MINIMUM_BARS["swing"]:
                failures.append(f"{symbol_key}: {len(candles)} bars; 60 required.")
                continue
            last = candles[-1]
            age, stale = core._age_report(last.timestamp, "swing")
            if stale:
                failures.append(f"{symbol_key}: stale latest candle ({age}).")
                continue
            closes = [c.close for c in candles]
            volumes = [c.volume for c in candles]
            sma20, sma50, sma200 = (core._sma(closes, n) for n in (20, 50, 200))
            rsi, atr = core._rsi(closes), core._atr(candles)
            baseline = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
            rvol = last.volume / baseline if baseline else None

            positive = int(sma20 is not None and last.close > sma20)
            negative = int(sma20 is not None and last.close < sma20)
            positive += int(sma50 is not None and last.close > sma50)
            negative += int(sma50 is not None and last.close < sma50)
            if sma20 is not None and sma50 is not None:
                positive += int(sma20 > sma50)
                negative += int(sma20 < sma50)
            if rsi is not None:
                positive += int(50 <= rsi < 70)
                negative += int(30 < rsi < 50)
            if rvol is not None and rvol >= 1.5:
                positive += int(last.close > last.open)
                negative += int(last.close < last.open)
            label = ("mixed evidence" if positive == negative else
                     "more positive conditions" if positive > negative else
                     "more negative conditions")
            rows.append({
                "symbol": symbol_key, "close": last.close,
                "change": (last.close / candles[-2].close - 1) * 100,
                "smas": (sma20, sma50, sma200), "rsi": rsi, "rvol": rvol,
                "atr_pct": atr / last.close * 100 if atr is not None else None,
                "positive": positive, "negative": negative, "label": label,
                "timestamp": last.timestamp.isoformat(), "source": source,
            })
        except core.MarketDataError as exc:
            failures.append(f"{symbol}: {exc}")

    rows.sort(key=lambda row: (row["positive"] - row["negative"], row["change"]), reverse=True)
    lines = [
        f"=== STOCK WATCHLIST SCREEN: {market_key.upper()} {exchange_key} ===",
        f"Interval: {interval_key} | Analyzed: {len(rows)}/{len(symbols)} | Provider: {core._provider.name}",
        "Evidence counts visible indicator conditions; this is a comparison, not a prediction.",
        "SYMBOL | CLOSE | BAR CHANGE | SMA20/50/200 | RSI14 | REL VOL20 | ATR% | EVIDENCE | LATEST CANDLE | SOURCE",
    ]
    for row in rows:
        smas = "/".join(core._fmt(value) for value in row["smas"])
        lines.append(
            f"{row['symbol']} | {core._fmt(row['close'])} | {row['change']:+.2f}% | {smas} | "
            f"{core._fmt(row['rsi'])} | {core._fmt(row['rvol'])}x | {core._fmt(row['atr_pct'])}% | "
            f"{row['positive']} positive / {row['negative']} negative ({row['label']}) | {row['timestamp']} | {row['source']}"
        )
    if failures:
        lines.append("\nNot analyzed: " + " ".join(failures))
    if not rows:
        lines.append("No symbols had enough fresh candle data to screen.")
    lines.extend([
        "",
        "This descriptive screen is not a forecast, personalized buy/sell recommendation, or order.",
        "Volume does not identify individual buyers, sellers, or verified order-flow direction.",
    ])
    return "\n".join(lines)
