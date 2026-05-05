from __future__ import annotations

"""
Parse Kalshi daily high-temperature market data into structured dicts.

Kalshi ticker format:
  {SERIES}-{YYMONDD}-{TYPE}{THRESHOLD}

Examples:
  KXHIGHTDAL-26MAY03-T79    → Dallas high temp < 79°F on May 3 2026  (bottom tail)
  KXHIGHTDAL-26MAY03-B79.5  → Dallas high temp 79–81°F on May 3 2026 (bucket)
  KXHIGHTDAL-26MAY03-T86    → Dallas high temp > 86°F on May 3 2026  (top tail)

Direction is determined from the title text (<, >, or a range like "79-81°").
Pricing comes from last_price_dollars (last traded price ≈ market probability).
"""

import re
from datetime import date, datetime
from config import TARGET_CITIES, SERIES_TO_CITY

CITY_LOOKUP = {c["name"]: c for c in TARGET_CITIES}


def parse_market(market: dict) -> dict | None:
    """
    Returns a parsed market dict or None if the market cannot be used.

    Returned keys:
      ticker, city, target_date, threshold_f, direction,
      low_f, high_f (bucket only), yes_price, no_price
    """
    ticker = market.get("ticker", "")
    title  = (market.get("title") or "").strip()

    # Pricing: last_price_dollars is the last traded price (≈ market probability)
    raw_price = market.get("last_price_dollars")
    if raw_price is None:
        return None
    try:
        market_prob = float(raw_price)
    except (ValueError, TypeError):
        return None

    # Skip contracts with no trading activity or pinned at the extremes
    if market_prob <= 0.01 or market_prob >= 0.99:
        return None

    # Ask prices (in cents from API; fall back to last price if unavailable)
    yes_ask_raw = market.get("yes_ask")
    no_ask_raw  = market.get("no_ask")
    yes_ask = (yes_ask_raw / 100) if (yes_ask_raw and 1 < yes_ask_raw < 99) else market_prob
    no_ask  = (no_ask_raw  / 100) if (no_ask_raw  and 1 < no_ask_raw  < 99) else round(1.0 - market_prob, 4)

    # Ticker must have at least 3 dash-separated parts
    parts = ticker.split("-")
    if len(parts) < 3:
        return None

    series   = parts[0]          # e.g. KXHIGHTDAL
    date_str = parts[1]          # e.g. 26MAY03
    type_str = parts[2]          # e.g. T79 or B79.5

    # Map series to city
    city_name = SERIES_TO_CITY.get(series)
    if not city_name:
        return None
    city = CITY_LOOKUP.get(city_name)
    if not city:
        return None

    # Parse the target date
    target_date = _parse_date(date_str)
    if not target_date:
        return None

    # Parse threshold and direction from the type code + title
    threshold_f, direction, low_f, high_f = _parse_type(type_str, title)
    if threshold_f is None or direction is None:
        return None

    return {
        "ticker":      ticker,
        "city":        city,
        "target_date": target_date,
        "threshold_f": threshold_f,
        "direction":   direction,   # "above", "below", or "bucket"
        "low_f":       low_f,       # bucket lower bound (or None)
        "high_f":      high_f,      # bucket upper bound (or None)
        "yes_price":   market_prob,
        "no_price":    round(1.0 - market_prob, 4),
        "yes_ask":     yes_ask,
        "no_ask":      no_ask,
        "raw":         market,
    }


def _parse_date(date_str: str) -> date | None:
    """'26MAY03' → date(2026, 5, 3)"""
    try:
        return datetime.strptime(date_str, "%y%b%d").date()
    except ValueError:
        return None


def _parse_type(type_str: str, title: str) -> tuple:
    """
    Returns (threshold_f, direction, low_f, high_f).

    T markets (tail contracts):
      Title contains '<' → direction = 'below'
      Title contains '>' → direction = 'above'

    B markets (bucket contracts):
      Title contains 'X–Y°' range → direction = 'bucket', low=X, high=Y
    """
    if type_str.startswith("T"):
        try:
            threshold = float(type_str[1:])
        except ValueError:
            return None, None, None, None

        if "<" in title:
            return threshold, "below", None, None
        else:
            return threshold, "above", None, None

    if type_str.startswith("B"):
        try:
            midpoint = float(type_str[1:])
        except ValueError:
            return None, None, None, None

        # Extract range from title: "79-80°" or "79–81°"
        m = re.search(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)', title)
        if m:
            low  = float(m.group(1))
            high = float(m.group(2))
        else:
            # Fallback: 2°F bucket centred on midpoint
            low  = midpoint - 1.0
            high = midpoint + 1.0

        return midpoint, "bucket", low, high

    return None, None, None, None
