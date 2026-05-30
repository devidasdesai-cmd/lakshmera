"""
Follow-up #2: fit σ for the V2 distribution-fit probability.

Reuses the cache of historical forecasts pulled by forecast_brier_may29.py.
Sweeps σ ∈ {1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 8}°F over the 433 settled bucket
trades and reports Brier per σ. Selects the σ that minimizes Brier.

Also computes per-city and per-direction breakdowns to see if σ should vary
(initial answer: don't bother — pick one global σ unless the spread is large).
"""
from __future__ import annotations
import os, sys, time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
import requests

from config import TARGET_CITIES, SERIES_TO_CITY
from weather import HISTORICAL_FORECAST_URL, norm_probability_between

CITY_LOOKUP = {c["name"]: c for c in TARGET_CITIES}
WINDOW_DAYS = 60
SIGMAS = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0]
MODEL = "gfs_seamless"   # best performer from the May 29 diagnostic


def conn(): return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def parse_target_date(ticker):
    parts = ticker.split("-")
    if len(parts) < 2: return None
    from datetime import datetime
    try: return datetime.strptime(parts[1], "%y%b%d").date()
    except ValueError: return None


def fetch_buckets():
    c = conn(); cur = c.cursor()
    cur.execute(f"""
      SELECT ticker, result FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND result IS NOT NULL
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
    """)
    rows = cur.fetchall(); cur.close(); c.close()
    out = []
    for tk, res in rows:
        parts = tk.split("-")
        if len(parts) < 3 or not parts[2].startswith("B"): continue
        city = SERIES_TO_CITY.get(parts[0])
        if not city: continue
        c_obj = CITY_LOOKUP.get(city)
        if not c_obj: continue
        td = parse_target_date(tk)
        if not td: continue
        try: midpoint = float(parts[2][1:])
        except ValueError: continue
        out.append({
            "ticker": tk, "city": city,
            "lat": c_obj["lat"], "lon": c_obj["lon"], "tz": c_obj["tz"],
            "target_date": td, "low_f": midpoint - 1.0, "high_f": midpoint + 1.0,
            "result": res,
        })
    return out


def fetch_forecast(lat, lon, target_date, tz):
    params = dict(latitude=lat, longitude=lon, daily="temperature_2m_max",
                  models=MODEL, start_date=target_date.isoformat(),
                  end_date=target_date.isoformat(),
                  temperature_unit="fahrenheit", timezone=tz)
    for attempt in range(2):
        try:
            r = requests.get(HISTORICAL_FORECAST_URL, params=params, timeout=20)
            r.raise_for_status()
            daily = r.json().get("daily", {})
            for k, v in daily.items():
                if k.startswith("temperature_2m_max") and v and v[0] is not None:
                    return float(v[0])
            return None
        except Exception:
            if attempt == 0: time.sleep(2)
    return None


def brier(preds, outcomes):
    return sum((p - y) ** 2 for p, y in zip(preds, outcomes)) / len(preds) if preds else 0.0


def main():
    rows = fetch_buckets()
    print(f"Bucket trades to evaluate: {len(rows)}")
    keys = list({(r["city"], r["target_date"]) for r in rows})
    print(f"Unique (city, date) combos: {len(keys)}")

    # Fetch forecasts (cache once)
    cache = {}
    print(f"Pulling {len(keys)} historical forecasts (~{len(keys) * 0.2 / 60:.1f} min)...")
    for i, key in enumerate(keys, 1):
        city, td = key
        c_obj = CITY_LOOKUP[city]
        cache[key] = fetch_forecast(c_obj["lat"], c_obj["lon"], td, c_obj["tz"])
        time.sleep(0.12)
        if i % 25 == 0: print(f"  ...{i}/{len(keys)}")
    print()

    outcomes = [1 if r["result"] == "yes" else 0 for r in rows]
    base = sum(outcomes) / len(outcomes)

    print("=" * 70)
    print(f"σ SWEEP — Brier on {len(rows)} bucket trades (gfs_seamless data)")
    print("=" * 70)
    print(f"  {'σ (°F)':<10} {'Brier':>10} {'vs σ=3':>10} {'vs baseline':>14}")
    base_brier = brier([base] * len(rows), outcomes)
    results = []
    for sigma in SIGMAS:
        preds = []
        for r in rows:
            t = cache.get((r["city"], r["target_date"]))
            if t is None:
                preds.append(base)
            else:
                p = norm_probability_between(t, r["low_f"], r["high_f"], sigma=sigma)
                preds.append(max(0.001, min(0.999, p)))
        b = brier(preds, outcomes)
        results.append((sigma, b))

    best_sigma, best_brier = min(results, key=lambda x: x[1])
    sigma3_brier = next(b for s, b in results if s == 3.0)
    for sigma, b in results:
        delta_sigma3 = b - sigma3_brier
        delta_baseline = b - base_brier
        flag = " ← BEST" if sigma == best_sigma else ""
        print(f"  {sigma:<10.1f} {b:>10.4f} {delta_sigma3:>+10.4f} {delta_baseline:>+14.4f}{flag}")
    print(f"\n  Baseline (constant {base*100:.0f}%): {base_brier:.4f}")
    print(f"  Best σ: {best_sigma}°F  →  Brier {best_brier:.4f}")

    # Reliability at the best σ
    print("\n" + "=" * 70)
    print(f"Reliability at σ = {best_sigma}°F")
    print("=" * 70)
    preds_best = []
    for r in rows:
        t = cache.get((r["city"], r["target_date"]))
        if t is None: preds_best.append(base)
        else:
            p = norm_probability_between(t, r["low_f"], r["high_f"], sigma=best_sigma)
            preds_best.append(max(0.001, min(0.999, p)))
    bands = [(0,0.05),(0.05,0.10),(0.10,0.15),(0.15,0.20),(0.20,0.25),
             (0.25,0.30),(0.30,0.40),(0.40,0.50),(0.50,1.01)]
    print(f"  {'Band':<13} {'N':>5} {'Actual YES':>11} {'Pred mid':>9}")
    for lo, hi in bands:
        sub = [(p, y) for p, y in zip(preds_best, outcomes) if lo <= p < hi]
        if not sub: continue
        n = len(sub); a = sum(y for _, y in sub) / n
        mid = (lo+hi)/2
        print(f"  {lo:.2f}-{hi:.2f}     {n:>4}  {a*100:>9.1f}%  {mid*100:>7.1f}%")

    # Per-city sigma fit (do some cities want a different sigma?)
    print("\n" + "=" * 70)
    print("Per-city σ sensitivity — does any city want a wildly different σ?")
    print("=" * 70)
    by_city = defaultdict(list)
    for i, r in enumerate(rows):
        by_city[r["city"]].append(i)
    print(f"  {'City':<14} {'N':>4} {'Best σ':>7} {'Brier':>8} {'vs σ=3':>10}")
    for city, idxs in sorted(by_city.items()):
        if len(idxs) < 10: continue   # skip tiny samples
        sub_outs = [outcomes[i] for i in idxs]
        best_s, best_b = None, 1.0
        for sigma in SIGMAS:
            preds = []
            for i in idxs:
                r = rows[i]
                t = cache.get((r["city"], r["target_date"]))
                if t is None: preds.append(base)
                else:
                    p = norm_probability_between(t, r["low_f"], r["high_f"], sigma=sigma)
                    preds.append(max(0.001, min(0.999, p)))
            b = brier(preds, sub_outs)
            if b < best_b:
                best_b = b; best_s = sigma
        # σ=3 Brier for the same city
        preds3 = []
        for i in idxs:
            r = rows[i]
            t = cache.get((r["city"], r["target_date"]))
            if t is None: preds3.append(base)
            else:
                p = norm_probability_between(t, r["low_f"], r["high_f"], sigma=3.0)
                preds3.append(max(0.001, min(0.999, p)))
        b3 = brier(preds3, sub_outs)
        print(f"  {city:<14} {len(idxs):>4}  {best_s:>5.1f}°F {best_b:>8.4f} {best_b - b3:>+10.4f}")


if __name__ == "__main__":
    main()
