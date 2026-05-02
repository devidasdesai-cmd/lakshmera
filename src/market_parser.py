"""
Parse Kalshi market data to extract the city, date, threshold, and direction
needed to run the probability model.

Kalshi weather market tickers follow patterns like:
  HIGHTEMP-DALLAS-24DEC25-T90   (Will Dallas high exceed 90°F on Dec 25 2024?)
  HIGHNY-25JAN10-T32            (Will NYC high exceed 32°F on Jan 10 2025?)

Title/subtitle text is the most reliable source — we parse that alongside
the ticker to extract structured data.

NOTE: Kalshi changes their naming conventions periodically. If markets stop
matching, print a raw market dict and update the parsing logic here.
"""

import re
from datetime import date, datetime
from config import TARGET_CITIES


CITY_ALIASES = {
    "DALLAS":   "Dallas",
    "DFW":      "Dallas",
    "HOUSTON":  "Houston",
    "IAH":      "Houston",
    "CHICAGO":  "Chicago",
    "ORD":      "Chicago",
    "NEWYORK":  "New York",
    "NYC":      "New York",
    "JFK":      "New York",
    "MIAMI":    "Miami",
    "MIA":      "Miami",
}

CITY_LOOKUP = {c["name"]: c for c in TARGET_CITIES}


def parse_market(market: dict) -> dict | None:
    """
    Attempt to extract structured data from a Kalshi market dict.
    Returns a parsed dict or None if the market is not a temperature contract
    for one of our target cities.

    Returned dict keys:
      ticker, city (dict from TARGET_CITIES), target_date (date),
      threshold_f (float), direction ('above'|'below'),
      yes_price (float 0–1), no_price (float 0–1)
    """
    ticker = market.get("ticker", "")
    title = market.get("title", "") or market.get("subtitle", "")

    # --- Extract temperature threshold ---
    # Look for patterns like T90, T-5, T78.5, "> 90°F", "above 78"
    threshold_f = _extract_threshold(ticker, title)
    if threshold_f is None:
        return None

    # --- Extract direction ---
    direction = _extract_direction(ticker, title)

    # --- Extract city ---
    city = _extract_city(ticker, title)
    if city is None:
        return None

    # --- Extract target date ---
    target_date = _extract_date(ticker, title, market)
    if target_date is None:
        return None

    # --- Extract market prices (Kalshi prices are in cents, 1–99) ---
    yes_ask = market.get("yes_ask")  # price to buy YES
    no_ask = market.get("no_ask")    # price to buy NO

    if yes_ask is None or no_ask is None:
        return None

    return {
        "ticker": ticker,
        "city": city,
        "target_date": target_date,
        "threshold_f": threshold_f,
        "direction": direction,
        "yes_price": yes_ask / 100,
        "no_price": no_ask / 100,
        "raw": market,
    }


def _extract_threshold(ticker: str, title: str) -> float | None:
    # Ticker pattern: T90, T-5, T78
    m = re.search(r"T(-?\d+(?:\.\d+)?)", ticker)
    if m:
        return float(m.group(1))
    # Title pattern: "90°F", "90 degrees", "above 90"
    m = re.search(r"(\d+(?:\.\d+)?)\s*°?F", title, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def _extract_direction(ticker: str, title: str) -> str:
    combined = (ticker + " " + title).upper()
    if any(w in combined for w in ["BELOW", "UNDER", "LOW", "COLD"]):
        return "below"
    return "above"  # default for high-temperature contracts


def _extract_city(ticker: str, title: str) -> dict | None:
    combined = (ticker + " " + title).upper()
    for alias, canonical in CITY_ALIASES.items():
        if alias in combined:
            return CITY_LOOKUP.get(canonical)
    return None


def _extract_date(ticker: str, title: str, market: dict) -> date | None:
    # Try Kalshi's close_time field first
    close_time = market.get("close_time") or market.get("expiration_time")
    if close_time:
        try:
            return datetime.fromisoformat(close_time.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            pass

    # Ticker date patterns: 24DEC25, 25JAN10, 20241225
    m = re.search(r"(\d{2})([A-Z]{3})(\d{2})", ticker)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)}{m.group(2)}{m.group(3)}", "%d%b%y").date()
        except ValueError:
            pass

    m = re.search(r"(\d{8})", ticker)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            pass

    return None
