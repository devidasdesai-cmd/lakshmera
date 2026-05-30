"""
Follow-up #3 (re-numbered): extend forecast Brier diagnostic to TAIL contracts.

Tail tickers (T-prefix) are either "above" or "below" — direction comes from
the contract title, not the ticker. We pull the Kalshi market once per unique
ticker to resolve direction, then run the same Brier comparison as
forecast_brier_may29.py but using norm_probability_above() / _below().

If tail also shows distribution-fit > baseline > current model, V2 is good
to ship across all directions. If tail is messier, we may need to disable
tail bets in V2 (already covered by BAN_TAIL_NO_BETS; YES tail is already off
via MAX_YES_BET_MARKET_PRICE = 0).
"""
from __future__ import annotations
import os, sys, time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
import requests

from config import TARGET_CITIES, SERIES_TO_CITY
from weather import (
    HISTORICAL_FORECAST_URL,
    norm_probability_above, norm_probability_below,
)
from kalshi_client import KalshiClient

CITY_LOOKUP = {c["name"]: c for c in TARGET_CITIES}
WINDOW_DAYS = 60
SIGMA_F = 1.5    # σ chosen from follow-up #2 (σ fit) — optimal on bucket data
MODELS = ["gfs_seamless", "ecmwf_ifs025"]


def conn(): return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def parse_target_date(ticker):
    parts = ticker.split("-")
    if len(parts) < 2: return None
    from datetime import datetime
    try: return datetime.strptime(parts[1], "%y%b%d").date()
    except ValueError: return None


def fetch_tails():
    c = conn(); cur = c.cursor()
    cur.execute(f"""
      SELECT ticker, our_probability::float, result
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND our_probability IS NOT NULL AND result IS NOT NULL
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
    """)
    rows = cur.fetchall(); cur.close(); c.close()
    out = []
    for tk, op, res in rows:
        parts = tk.split("-")
        if len(parts) < 3 or not parts[2].startswith("T"): continue
        city = SERIES_TO_CITY.get(parts[0])
        if not city: continue
        c_obj = CITY_LOOKUP.get(city)
        if not c_obj: continue
        td = parse_target_date(tk)
        if not td: continue
        try: threshold = float(parts[2][1:])
        except ValueError: continue
        out.append({
            "ticker": tk, "city": city,
            "lat": c_obj["lat"], "lon": c_obj["lon"], "tz": c_obj["tz"],
            "target_date": td, "threshold": threshold,
            "our_prob": op, "result": res,
            "direction": None,  # to be filled
        })
    return out


def resolve_directions(rows):
    """Fetch each unique ticker once to determine above vs below from title."""
    client = KalshiClient()
    unique = list({r["ticker"] for r in rows})
    print(f"  Resolving direction for {len(unique)} unique tickers via Kalshi...")
    dir_cache = {}
    for i, tk in enumerate(unique, 1):
        try:
            mkt = client.get_market(tk)
            title = (mkt.get("title") or "").strip()
            if "<" in title: dir_cache[tk] = "below"
            elif ">" in title: dir_cache[tk] = "above"
            else: dir_cache[tk] = None
        except Exception:
            dir_cache[tk] = None
        if i % 25 == 0: print(f"    ...{i}/{len(unique)}")
        time.sleep(0.04)
    for r in rows:
        r["direction"] = dir_cache.get(r["ticker"])
    resolved = sum(1 for r in rows if r["direction"])
    print(f"  Resolved: {resolved}/{len(rows)} ({resolved/len(rows)*100:.1f}%)\n")
    return rows


def fetch_forecast(lat, lon, target_date, tz, model):
    params = dict(latitude=lat, longitude=lon, daily="temperature_2m_max",
                  models=model, start_date=target_date.isoformat(),
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
    rows = fetch_tails()
    print(f"Settled tail trades: {len(rows)}\n")
    rows = resolve_directions(rows)
    rows = [r for r in rows if r["direction"] in ("above", "below")]
    print(f"After direction filter: {len(rows)} usable tail trades\n")

    # Fetch historical forecasts per (city, date)
    keys = list({(r["city"], r["target_date"]) for r in rows})
    print(f"Unique (city, date): {len(keys)} → fetching {len(keys) * len(MODELS)} forecasts...\n")
    cache = {k: {} for k in keys}
    for i, key in enumerate(keys, 1):
        c_obj = CITY_LOOKUP[key[0]]
        for m in MODELS:
            cache[key][m] = fetch_forecast(c_obj["lat"], c_obj["lon"], key[1], c_obj["tz"], m)
            time.sleep(0.12)
        if i % 20 == 0: print(f"  ...{i}/{len(keys)}")
    print()

    outcomes = [1 if r["result"] == "yes" else 0 for r in rows]
    base = sum(outcomes) / len(outcomes)

    print("=" * 90)
    print(f"BRIER — TAIL contracts ({len(rows)} trades)")
    print("=" * 90)
    # Current model
    current_preds = [r["our_prob"] for r in rows]
    print(f"  Constant baseline ({base*100:.1f}%): {brier([base]*len(rows), outcomes):.4f}")
    print(f"  Current model:                       {brier(current_preds, outcomes):.4f}")
    # Distribution-fit per model
    for m in MODELS:
        preds = []
        for r in rows:
            t = cache.get((r["city"], r["target_date"]), {}).get(m)
            if t is None: preds.append(base)
            else:
                if r["direction"] == "above":
                    p = norm_probability_above(t, r["threshold"], sigma=SIGMA_F)
                else:
                    p = norm_probability_below(t, r["threshold"], sigma=SIGMA_F)
                preds.append(max(0.001, min(0.999, p)))
        print(f"  {m} + dist-fit (σ={SIGMA_F}):    {brier(preds, outcomes):.4f}")

    # Direction breakdown
    print("\n" + "=" * 90)
    print("Above vs Below — does direction matter?")
    print("=" * 90)
    for d in ("above", "below"):
        sub = [r for r in rows if r["direction"] == d]
        if not sub: continue
        s_outs = [1 if r["result"] == "yes" else 0 for r in sub]
        s_base = sum(s_outs)/len(s_outs)
        s_const = brier([s_base]*len(sub), s_outs)
        s_cur = brier([r["our_prob"] for r in sub], s_outs)
        s_gfs = []
        for r in sub:
            t = cache.get((r["city"], r["target_date"]), {}).get("gfs_seamless")
            if t is None: s_gfs.append(s_base)
            else:
                if d == "above": p = norm_probability_above(t, r["threshold"], sigma=SIGMA_F)
                else: p = norm_probability_below(t, r["threshold"], sigma=SIGMA_F)
                s_gfs.append(max(0.001, min(0.999, p)))
        print(f"\n  {d} (N={len(sub)}, actual YES = {s_base*100:.1f}%):")
        print(f"    Constant:      {s_const:.4f}")
        print(f"    Current model: {s_cur:.4f}")
        print(f"    GFS + dist-fit: {brier(s_gfs, s_outs):.4f}")


if __name__ == "__main__":
    main()
