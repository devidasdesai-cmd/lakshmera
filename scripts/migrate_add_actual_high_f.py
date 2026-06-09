"""
Adds actual_high_f (DECIMAL(5,2)) to the trades table for storing the
observed high temperature on settlement day. NULLable — only populated for
settled temperature trades. Rain trades stay NULL (different math).

Then backfills existing settled temperature trades by querying Open-Meteo's
archive API for each unique (city, target_date) pair, with a small in-script
cache to avoid redundant API calls.

Run after: src/settler.py updated to populate this column going forward.
"""
from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
import requests

from config import TARGET_CITIES

SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

CITY_LOOKUP = {c["name"]: c for c in TARGET_CITIES}


def fetch_actual(lat, lon, target_date_iso, tz):
    """Returns observed high temp (°F) or None."""
    try:
        r = requests.get(ARCHIVE_URL, params=dict(
            latitude=lat, longitude=lon, daily="temperature_2m_max",
            start_date=target_date_iso, end_date=target_date_iso,
            temperature_unit="fahrenheit", timezone=tz,
        ), timeout=15)
        r.raise_for_status()
        daily = r.json().get("daily", {})
        vals = daily.get("temperature_2m_max") or []
        return float(vals[0]) if vals and vals[0] is not None else None
    except Exception as e:
        print(f"  Open-Meteo error for ({lat},{lon}) {target_date_iso}: {e}")
        return None


def parse_city_from_ticker(ticker):
    """Map series prefix → city name."""
    series = ticker.split("-", 1)[0]
    M = {
        "KXHIGHTDAL": "Dallas", "KXHIGHTHOU": "Houston", "KXHIGHNY": "New York",
        "KXHIGHNY0": "New York", "KXHIGHTBOS": "Boston", "KXHIGHTMIN": "Minneapolis",
        "KXHIGHLAX": "Los Angeles", "KXHIGHTPHX": "Phoenix", "KXHIGHTDC": "DC",
        "KXHIGHTLV": "Las Vegas", "KXHIGHTSEA": "Seattle",
        "KXHIGHTSATX": "San Antonio", "KXHIGHTSFO": "San Francisco",
        "KXHIGHTOKC": "Oklahoma City",
    }
    return M.get(series)


def parse_target_date_iso(ticker):
    """26JUN08 → 2026-06-08."""
    parts = ticker.split("-")
    if len(parts) < 2: return None
    from datetime import datetime
    try:
        return datetime.strptime(parts[1], "%y%b%d").date().isoformat()
    except ValueError:
        return None


def main():
    conn = psycopg2.connect(SUPABASE_DB_URL)
    cur = conn.cursor()

    print("1. Adding actual_high_f column...")
    cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS actual_high_f DECIMAL(5,2);")
    conn.commit()
    print("   ✓ done.")

    print()
    print("2. Backfilling existing settled temperature trades...")
    cur.execute("""
      SELECT id, ticker FROM trades
      WHERE paper_trade = TRUE AND settled = TRUE
        AND actual_high_f IS NULL
        AND ticker NOT LIKE 'KXRAIN%'
    """)
    rows = cur.fetchall()
    print(f"   {len(rows)} settled temp trades to backfill.")
    if not rows:
        cur.close(); conn.close()
        return

    cache: dict[tuple, float | None] = {}
    updated = 0
    skipped = 0
    for trade_id, ticker in rows:
        city_name = parse_city_from_ticker(ticker)
        if not city_name:
            skipped += 1; continue
        city = CITY_LOOKUP.get(city_name)
        if not city:
            skipped += 1; continue
        target_date_iso = parse_target_date_iso(ticker)
        if not target_date_iso:
            skipped += 1; continue

        key = (city_name, target_date_iso)
        if key not in cache:
            cache[key] = fetch_actual(city["lat"], city["lon"], target_date_iso, city["tz"])
            time.sleep(0.08)  # be polite to Open-Meteo
        actual = cache[key]
        if actual is None:
            skipped += 1; continue

        cur.execute("UPDATE trades SET actual_high_f = %s WHERE id = %s", (actual, trade_id))
        updated += 1
        if updated % 50 == 0:
            conn.commit()
            print(f"   ...{updated} backfilled (cache size {len(cache)})")

    conn.commit()
    print()
    print(f"   ✓ Backfilled {updated} trades. Skipped {skipped} (unparseable or no data).")
    print(f"   Unique (city, date) pairs queried: {len(cache)}")

    cur.close(); conn.close()


if __name__ == "__main__":
    main()
