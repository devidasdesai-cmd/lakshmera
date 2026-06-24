"""
Re-fetch actual_high_f from NWS CLI for all settled temperature trades.
NWS CLI is Kalshi's settlement source — reconciles with WIN/LOSS cleanly,
unlike Open-Meteo which can disagree by several degrees.

For trades older than ~7-14 days, NWS CLI won't be available and the
existing Open-Meteo value is left in place.

Idempotent: safe to re-run; only updates when NWS returns a value.
"""
from __future__ import annotations
import os, sys, time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

from weather import get_nws_cli_high_f
from config import SERIES_TO_CITY


def main():
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()

    cur.execute("""
      SELECT id, ticker, actual_high_f
      FROM trades
      WHERE paper_trade = TRUE AND settled = TRUE
        AND ticker NOT LIKE 'KXRAIN%'
      ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    print(f"Considering {len(rows)} settled temperature trades.")

    cache: dict[tuple, float | None] = {}
    nws_found = 0
    updated = 0
    same = 0
    skipped_old = 0
    diffs: list[tuple] = []

    for trade_id, ticker, old_actual in rows:
        parts = ticker.split("-")
        if len(parts) < 2: continue
        city_name = SERIES_TO_CITY.get(parts[0])
        if not city_name: continue
        try:
            target_date = datetime.strptime(parts[1], "%y%b%d").date()
        except ValueError:
            continue

        key = (city_name, target_date.isoformat())
        if key in cache:
            v = cache[key]
        else:
            v = get_nws_cli_high_f(city_name, target_date)
            cache[key] = v
            time.sleep(0.1)

        if v is None:
            skipped_old += 1
            continue

        nws_found += 1
        old_f = float(old_actual) if old_actual is not None else None
        if old_f is None or abs(old_f - v) >= 0.1:
            cur.execute("UPDATE trades SET actual_high_f = %s WHERE id = %s", (v, trade_id))
            updated += 1
            if old_f is not None:
                diffs.append((ticker, old_f, v, v - old_f))
        else:
            same += 1

        if updated and updated % 50 == 0:
            conn.commit()
            print(f"  ...{updated} updated, {same} unchanged, {skipped_old} no-NWS")

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nDone:")
    print(f"  NWS values found: {nws_found}")
    print(f"  Updated to NWS value: {updated}")
    print(f"  Already matched NWS: {same}")
    print(f"  Skipped (NWS unavailable; OM value retained): {skipped_old}")

    if diffs:
        print(f"\nLargest discrepancies (where NWS disagrees with old OM value):")
        diffs.sort(key=lambda x: -abs(x[3]))
        for tk, old, new, delta in diffs[:15]:
            print(f"  {tk:<28}  OM={old:.1f}°F  →  NWS={new:.1f}°F  (Δ={delta:+.1f}°F)")


if __name__ == "__main__":
    main()
