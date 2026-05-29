"""
Historical forecast diagnostic — does a different data source beat our current
model on Brier score?

Pulls archived deterministic forecasts (GFS short-range, ECMWF deterministic,
Open-Meteo best_match) for each settled BUCKET trade in our DB. Computes a
distribution-fit probability (normal CDF around the forecast with σ=3°F).
Compares Brier scores against current bot + constant baseline.

Bucket-only for this first cut because the direction is unambiguous from the
ticker — no Kalshi lookup needed for ~430 trades.

If any forecast source meaningfully beats the 0.1686 bucket constant baseline,
we have evidence that data quality (not just calibration) is a real lever.
"""
from __future__ import annotations
import os, sys, time, math
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
import requests

from config import TARGET_CITIES, SERIES_TO_CITY
from weather import (
    HISTORICAL_FORECAST_URL,
    norm_probability_between,
)

CITY_LOOKUP = {c["name"]: c for c in TARGET_CITIES}

WINDOW_DAYS = 60
SIGMA_F = 3.0   # forecast error std dev assumed for distribution fit (typical short-range)
MODELS  = ["gfs_seamless", "ecmwf_ifs025", "best_match"]


def conn():
    return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def fetch_settled_buckets():
    """
    Returns list of dicts: ticker, city, lat, lon, tz, target_date (str),
    low_f, high_f, our_prob, result.
    Bucket tickers only — third dash-segment starts with 'B'.
    """
    c = conn(); cur = c.cursor()
    cur.execute(f"""
      SELECT ticker, our_probability::float, result, created_at::date
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND our_probability IS NOT NULL AND result IS NOT NULL
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
    """)
    rows = cur.fetchall()
    cur.close(); c.close()

    out = []
    for tk, op, res, _ in rows:
        parts = tk.split("-")
        if len(parts) < 3: continue
        series, date_str, type_str = parts[0], parts[1], parts[2]
        if not type_str.startswith("B"): continue
        city_name = SERIES_TO_CITY.get(series)
        if not city_name: continue
        city = CITY_LOOKUP.get(city_name)
        if not city: continue

        # Date
        from datetime import datetime
        try:
            target_date = datetime.strptime(date_str, "%y%b%d").date()
        except ValueError:
            continue

        # Bucket bounds — midpoint ±1 (matches the fallback in market_parser)
        try:
            midpoint = float(type_str[1:])
        except ValueError:
            continue
        low_f = midpoint - 1.0
        high_f = midpoint + 1.0

        out.append({
            "ticker": tk, "city": city["name"],
            "lat": city["lat"], "lon": city["lon"], "tz": city["tz"],
            "target_date": target_date, "low_f": low_f, "high_f": high_f,
            "our_prob": op, "result": res,
        })
    return out


def fetch_historical(lat, lon, target_date, tz, model):
    """Returns single forecast temp or None."""
    params = {
        "latitude": lat, "longitude": lon, "daily": "temperature_2m_max",
        "models": model,
        "start_date": target_date.isoformat(),
        "end_date":   target_date.isoformat(),
        "temperature_unit": "fahrenheit", "timezone": tz,
    }
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
            if attempt == 0:
                time.sleep(2)
            else:
                return None


def brier(preds, outcomes):
    return sum((p - y) ** 2 for p, y in zip(preds, outcomes)) / len(preds) if preds else 0.0


def main():
    print(f"Pulling settled bucket trades (last {WINDOW_DAYS} days)...")
    rows = fetch_settled_buckets()
    print(f"  {len(rows)} bucket trades to evaluate.\n")

    # Group by (city, target_date) so we hit the API once per unique combo
    keys = list({(r["city"], r["target_date"]) for r in rows})
    print(f"  Unique (city, target_date) combos: {len(keys)}")
    print(f"  Total API calls needed: {len(keys) * len(MODELS)}  (estimated {len(keys) * len(MODELS) * 0.4 / 60:.1f} min)\n")

    # Cache
    cache: dict[tuple, dict[str, float | None]] = {}
    for i, key in enumerate(keys, 1):
        city, td = key
        city_obj = CITY_LOOKUP.get(city)
        if not city_obj:
            cache[key] = {m: None for m in MODELS}; continue
        cache[key] = {}
        for m in MODELS:
            cache[key][m] = fetch_historical(city_obj["lat"], city_obj["lon"], td, city_obj["tz"], m)
            time.sleep(0.15)  # be polite
        if i % 20 == 0:
            done_pct = i / len(keys) * 100
            print(f"  ...{i}/{len(keys)} ({done_pct:.0f}%)")

    # Now compute Brier per strategy
    outcomes = [1 if r["result"] == "yes" else 0 for r in rows]
    base_rate = sum(outcomes) / len(outcomes)
    print(f"\nBucket base rate (actual YES): {base_rate*100:.1f}%\n")

    series = {
        "Constant baseline": [base_rate] * len(rows),
        "Current model":     [r["our_prob"] for r in rows],
    }
    for m in MODELS:
        preds = []
        for r in rows:
            t = cache.get((r["city"], r["target_date"]), {}).get(m)
            if t is None:
                preds.append(base_rate)  # fallback when forecast missing
            else:
                p = norm_probability_between(t, r["low_f"], r["high_f"], sigma=SIGMA_F)
                preds.append(max(0.001, min(0.999, p)))
        series[f"{m} + distribution-fit (σ={SIGMA_F})"] = preds

    print("=" * 90)
    print("BRIER SCORES — bucket contracts only (lower = better)")
    print("=" * 90)
    for label, preds in series.items():
        b = brier(preds, outcomes)
        delta = b - brier(series["Constant baseline"], outcomes)
        marker = " ★" if (label != "Constant baseline" and b < brier(series["Constant baseline"], outcomes)) else ""
        print(f"  {label:<45}  Brier = {b:.4f}  ({delta:+.4f} vs baseline){marker}")

    # Calibration plot per strategy
    print("\n" + "=" * 90)
    print("RELIABILITY by predicted-probability decile (does any strategy track reality?)")
    print("=" * 90)
    bands = [(0,0.10),(0.10,0.20),(0.20,0.30),(0.30,0.50),(0.50,1.01)]
    for label, preds in series.items():
        if label == "Constant baseline": continue
        print(f"\n  {label}:")
        print(f"    {'Band':<13} {'N':>4} {'Actual YES':>11} {'Pred mid':>9}")
        for lo, hi in bands:
            sub = [(p, y) for p, y in zip(preds, outcomes) if lo <= p < hi]
            if not sub: continue
            n = len(sub); a = sum(y for _, y in sub) / n
            mid = (lo + hi) / 2
            print(f"    {lo:.2f}-{hi:.2f}    {n:>4} {a*100:>9.1f}%  {mid*100:>7.1f}%")

    # Spread of predictions — does the new source actually produce varied numbers?
    print("\n" + "=" * 90)
    print("PREDICTION SPREAD (does the alternative source even disagree across contracts?)")
    print("=" * 90)
    for label, preds in series.items():
        lo = min(preds); hi = max(preds); avg = sum(preds) / len(preds)
        print(f"  {label:<45}  min={lo*100:>4.1f}% max={hi*100:>5.1f}% mean={avg*100:>5.1f}%")


if __name__ == "__main__":
    main()
