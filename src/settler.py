from __future__ import annotations
"""
Checks all unsettled trades in the DB against the Kalshi API.
When a market has resolved, records the result and calculates P&L.

P&L logic:
  Each Kalshi contract pays $1.00 if your side wins.
  You spent `price_paid` per contract.
  win:  pnl = contract_count * (1.00 - price_paid)
  lose: pnl = -contract_count * price_paid  (≈ -amount_usd)
"""

from datetime import datetime

import requests

from config import TARGET_CITIES, SERIES_TO_CITY
from database import get_connection
from kalshi_client import KalshiClient

_CITY_LOOKUP = {c["name"]: c for c in TARGET_CITIES}
_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def _fetch_actual_high_f(ticker: str, cache: dict) -> float | None:
    """
    Look up the actual high temp (°F) for a temperature trade from Open-Meteo's
    archive. Caches per (city, target_date) within a single settler run.
    Returns None for rain tickers, unparseable tickers, or API failures —
    settler should not crash if we can't get this number.
    """
    if ticker.startswith("KXRAIN"):
        return None
    parts = ticker.split("-")
    if len(parts) < 2:
        return None
    series = parts[0]
    city_name = SERIES_TO_CITY.get(series)
    if not city_name:
        return None
    city = _CITY_LOOKUP.get(city_name)
    if not city:
        return None
    try:
        target_date = datetime.strptime(parts[1], "%y%b%d").date()
    except ValueError:
        return None

    key = (city_name, target_date.isoformat())
    if key in cache:
        return cache[key]

    try:
        r = requests.get(_ARCHIVE_URL, params=dict(
            latitude=city["lat"], longitude=city["lon"],
            daily="temperature_2m_max",
            start_date=target_date.isoformat(), end_date=target_date.isoformat(),
            temperature_unit="fahrenheit", timezone=city["tz"],
        ), timeout=10)
        r.raise_for_status()
        vals = (r.json().get("daily", {}) or {}).get("temperature_2m_max") or []
        v = float(vals[0]) if vals and vals[0] is not None else None
    except Exception as e:
        print(f"  Open-Meteo archive lookup failed for {ticker}: {e}")
        v = None
    cache[key] = v
    return v


def settle_trades():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ticker, side, amount_usd, contract_count, price_paid, market_probability
        FROM trades
        WHERE settled = FALSE
        ORDER BY created_at
        """
    )
    unsettled = cur.fetchall()

    if not unsettled:
        print("Settlement check: no unsettled trades.")
        cur.close()
        conn.close()
        return

    print(f"Settlement check: {len(unsettled)} unsettled trade(s)...")
    client = KalshiClient()
    settled_count = 0
    actual_cache: dict = {}

    for row in unsettled:
        trade_id, ticker, side, amount_usd, contract_count, price_paid, market_prob = row

        try:
            market = client.get_market(ticker)
        except Exception as e:
            print(f"  {ticker}: API error — {e}")
            continue

        result = market.get("result", "")
        if result not in ("yes", "no"):
            continue  # Market not resolved yet

        # Derive price_paid for trades logged before this column was added
        if price_paid is None:
            price_paid = float(market_prob) if side == "yes" else (1.0 - float(market_prob))

        price_paid = float(price_paid)
        amount_usd = float(amount_usd)

        # Derive contract_count for legacy trades
        if contract_count is None:
            contract_count = max(1, round(amount_usd / price_paid))

        contract_count = int(contract_count)

        if result == side:
            pnl = round(contract_count * (1.0 - price_paid), 2)
        else:
            pnl = round(-contract_count * price_paid, 2)

        # Observed high temp for the contract date — informational, used by
        # the dashboard to show actual vs forecast deltas. NULL for rain trades.
        actual_high_f = _fetch_actual_high_f(ticker, actual_cache)

        cur.execute(
            "UPDATE trades SET settled=TRUE, result=%s, pnl=%s, actual_high_f=%s WHERE id=%s",
            (result, pnl, actual_high_f, trade_id),
        )
        settled_count += 1
        outcome = "WON" if result == side else "LOST"
        actual_str = f", actual {actual_high_f:.1f}°F" if actual_high_f is not None else ""
        print(f"  {ticker}: {outcome} ({side.upper()} @ {price_paid:.2f}) | pnl ${pnl:+.2f}{actual_str}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Settlement complete: {settled_count} trade(s) settled.\n")
