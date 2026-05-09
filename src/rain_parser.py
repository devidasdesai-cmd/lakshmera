from __future__ import annotations

"""
Parse Kalshi monthly precipitation market tickers into structured dicts.

Ticker format:  {SERIES}-{YYMON}-{THRESHOLD_INCHES}
Example:        KXRAINDALM-26MAY-3  →  Dallas, May 2026, total rainfall > 3 inches

All rain markets are "above" contracts: YES resolves if monthly total exceeds threshold.
"""

import calendar
from datetime import date, datetime
from config import RAIN_SERIES_TO_CITY, TARGET_CITIES

CITY_LOOKUP = {c["name"]: c for c in TARGET_CITIES}


def parse_rain_market(market: dict) -> dict | None:
    """
    Returns a parsed rain market dict or None if the market cannot be used.

    Returned keys:
      ticker, city, year, month, month_end, threshold_inches,
      yes_price, no_price, yes_ask, no_ask
    """
    ticker = market.get("ticker", "")

    raw_price = market.get("last_price_dollars")
    if raw_price is None:
        return None
    try:
        market_prob = float(raw_price)
    except (ValueError, TypeError):
        return None

    if market_prob <= 0.01 or market_prob >= 0.99:
        return None

    parts = ticker.split("-")
    if len(parts) < 3:
        return None

    series    = parts[0]   # e.g. KXRAINDALM
    month_str = parts[1]   # e.g. 26MAY
    thresh_str = parts[2]  # e.g. 3

    city_name = RAIN_SERIES_TO_CITY.get(series)
    if not city_name:
        return None
    city = CITY_LOOKUP.get(city_name)
    if not city:
        return None

    try:
        d = datetime.strptime(month_str, "%y%b")
        year, month = d.year, d.month
    except ValueError:
        return None

    try:
        threshold_inches = float(thresh_str)
    except ValueError:
        return None

    last_day = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)

    # Rain markets expose ask prices as dollars (strings), not cents
    yes_ask_raw = market.get("yes_ask_dollars")
    no_ask_raw  = market.get("no_ask_dollars")
    try:
        yes_ask = float(yes_ask_raw) if yes_ask_raw else market_prob
        no_ask  = float(no_ask_raw)  if no_ask_raw  else round(1.0 - market_prob, 4)
    except (ValueError, TypeError):
        yes_ask = market_prob
        no_ask  = round(1.0 - market_prob, 4)

    return {
        "ticker":           ticker,
        "city":             city,
        "year":             year,
        "month":            month,
        "month_end":        month_end,
        "threshold_inches": threshold_inches,
        "yes_price":        market_prob,
        "no_price":         round(1.0 - market_prob, 4),
        "yes_ask":          yes_ask,
        "no_ask":           no_ask,
        "raw":              market,
    }
