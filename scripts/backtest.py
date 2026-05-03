"""
Approximate backtesting script for Lakshmera weather bot.

Usage:
  python scripts/backtest.py --start 2026-04-21 --end 2026-04-27 --run-id apr21-27

Fetches settled Kalshi markets for the date range, runs the bot's probability
estimation against historical GFS forecasts, and stores results to backtest_trades.
"""

from __future__ import annotations
import argparse
import os
import sys
from datetime import date

# Load local.env if present — handles multi-line values (e.g. RSA private keys)
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'local.env')
if os.path.exists(_env_file):
    _cur_key, _cur_val = None, []
    def _flush():
        if _cur_key:
            os.environ[_cur_key] = ''.join(_cur_val)
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.rstrip('\n')
            if _line.startswith('#') or not _line.strip():
                continue
            if '=' in _line and not _line[0].isspace():
                _flush()
                _cur_key, _, _v = _line.partition('=')
                _cur_key = _cur_key.strip()
                _cur_val = [_v]
            elif _cur_key:
                _cur_val.append(_line)
    _flush()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

import psycopg2

from config import (
    SUPABASE_DB_URL,
    TARGET_SERIES,
    SERIES_TO_CITY,
    MIN_EDGE_THRESHOLD,
    MAX_EDGE_THRESHOLD,
    STARTING_CAPITAL,
    MAX_TRADE_SIZE_USD,
    KELLY_CAP,
)
from kalshi_client import KalshiClient
from market_parser import _parse_date, _parse_type, CITY_LOOKUP
from model import calculate_edge, kelly_size
from weather import (
    get_historical_forecast_temps,
    probability_above, probability_below, probability_between,
    norm_probability_above, norm_probability_below, norm_probability_between,
)


def _parse_market_backtest(market: dict) -> dict | None:
    """
    Like market_parser.parse_market but uses a wider price filter.
    Settled markets trend toward 0 or 1, so we widen to 0.02–0.98 to capture
    markets that hadn't fully converged to settlement price.
    """
    ticker = market.get("ticker", "")
    title = (market.get("title") or "").strip()

    raw_price = market.get("last_price_dollars")
    if raw_price is None:
        return None
    try:
        market_prob = float(raw_price)
    except (ValueError, TypeError):
        return None

    if market_prob < 0.02 or market_prob > 0.98:
        return None

    parts = ticker.split("-")
    if len(parts) < 3:
        return None

    series = parts[0]
    date_str = parts[1]
    type_str = parts[2]

    city_name = SERIES_TO_CITY.get(series)
    if not city_name:
        return None
    city = CITY_LOOKUP.get(city_name)
    if not city:
        return None

    target_date = _parse_date(date_str)
    if not target_date:
        return None

    threshold_f, direction, low_f, high_f = _parse_type(type_str, title)
    if threshold_f is None or direction is None:
        return None

    return {
        "ticker": ticker,
        "city": city,
        "target_date": target_date,
        "threshold_f": threshold_f,
        "direction": direction,
        "low_f": low_f,
        "high_f": high_f,
        "yes_price": market_prob,
        "no_price": round(1.0 - market_prob, 4),
    }


def _estimate_prob(temps: list[float], direction: str, threshold_f: float,
                   low_f: float, high_f: float) -> float | None:
    if len(temps) > 1:
        if direction == "above":
            return probability_above(temps, threshold_f)
        elif direction == "below":
            return probability_below(temps, threshold_f)
        elif direction == "bucket":
            return probability_between(temps, low_f, high_f)
    elif len(temps) == 1:
        t = temps[0]
        if direction == "above":
            return norm_probability_above(t, threshold_f)
        elif direction == "below":
            return norm_probability_below(t, threshold_f)
        elif direction == "bucket":
            return norm_probability_between(t, low_f, high_f)
    return None


def run_backtest(start_date: date, end_date: date, run_id: str):
    print(f"\n{'='*60}")
    print(f"LAKSHMERA BACKTEST — {run_id}")
    print(f"Period: {start_date} to {end_date}")
    print(f"{'='*60}\n")

    client = KalshiClient()

    print("Fetching settled Kalshi markets...")
    all_markets = []
    for series in TARGET_SERIES:
        events = client.get_all_events(series_ticker=series, status="settled")
        for event in events:
            for m in event.get("markets", []):
                all_markets.append(m)
    print(f"Total settled markets fetched: {len(all_markets)}\n")

    # Filter to date range and require a valid result field
    relevant = []
    for market in all_markets:
        result = market.get("result")
        if result not in ("yes", "no"):
            continue
        parsed = _parse_market_backtest(market)
        if parsed is None:
            continue
        if not (start_date <= parsed["target_date"] <= end_date):
            continue
        relevant.append((parsed, result))

    print(f"Markets in date range with usable prices and results: {len(relevant)}\n")

    if not relevant:
        print("No markets to process. The date range may predate available data,")
        print("or settled markets may have last_price_dollars outside 0.02–0.98.")
        print("Try a more recent date range (last 30-60 days).")
        return

    # Pre-fetch historical GFS forecasts — one call per (city, date)
    print("Fetching historical GFS forecasts...")
    temp_cache: dict[tuple, list[float]] = {}
    city_dates = {(m["city"]["name"], m["target_date"]): m["city"] for m, _ in relevant}
    for (city_name, target_date), city in city_dates.items():
        temps = get_historical_forecast_temps(city["lat"], city["lon"], target_date, city["tz"])
        temp_cache[(city_name, target_date)] = temps
        if temps:
            mean = sum(temps) / len(temps)
            label = f"{len(temps)} member(s) | mean={mean:.1f}°F"
        else:
            label = "no data"
        print(f"  {city_name} {target_date}: {label}")
    print()

    # Evaluate each market
    rows = []
    for parsed, result in relevant:
        city = parsed["city"]
        ticker = parsed["ticker"]
        target_date = parsed["target_date"]
        threshold_f = parsed["threshold_f"]
        direction = parsed["direction"]
        low_f = parsed["low_f"]
        high_f = parsed["high_f"]
        yes_price = parsed["yes_price"]

        temps = temp_cache.get((city["name"], target_date), [])
        if not temps:
            continue

        our_prob = _estimate_prob(temps, direction, threshold_f, low_f, high_f)
        if our_prob is None:
            continue

        edge = calculate_edge(our_prob, yes_price)

        if abs(edge) < MIN_EDGE_THRESHOLD:
            action = "NO_BET"
        elif abs(edge) > MAX_EDGE_THRESHOLD:
            action = "SUSPICIOUS_EDGE"
        elif edge > 0:
            action = "BET_YES"
        else:
            action = "BET_NO"

        contract_count = None
        price_paid = None
        pnl = None
        side = None

        if action in ("BET_YES", "BET_NO"):
            bet_usd = min(kelly_size(abs(edge), STARTING_CAPITAL, KELLY_CAP), MAX_TRADE_SIZE_USD)
            bet_usd = max(round(bet_usd), 5)
            side = "yes" if action == "BET_YES" else "no"
            price = yes_price if side == "yes" else parsed["no_price"]
            contract_count = min(200, max(1, int((bet_usd * 100) / (price * 100))))
            price_paid = price

            won = (side == "yes" and result == "yes") or (side == "no" and result == "no")
            pnl = round(contract_count * (1.0 - price_paid), 4) if won \
                else round(-contract_count * price_paid, 4)

        rows.append({
            "run_id": run_id,
            "ticker": ticker,
            "city": city["name"],
            "target_date": target_date,
            "side": side,
            "our_probability": round(our_prob, 4),
            "market_probability": round(yes_price, 4),
            "edge": round(edge, 4),
            "action": action,
            "contract_count": contract_count,
            "price_paid": price_paid,
            "result": result,
            "pnl": pnl,
        })

    print(f"Evaluated {len(rows)} markets.\n")

    # Write to database
    conn = psycopg2.connect(SUPABASE_DB_URL)
    cur = conn.cursor()

    cur.execute("DELETE FROM backtest_trades WHERE run_id = %s", (run_id,))
    deleted = cur.rowcount
    if deleted > 0:
        print(f"Replaced {deleted} existing rows for run '{run_id}'.")

    for r in rows:
        cur.execute("""
            INSERT INTO backtest_trades
              (run_id, ticker, city, target_date, side, our_probability,
               market_probability, edge, action, contract_count, price_paid, result, pnl)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            r["run_id"], r["ticker"], r["city"], r["target_date"], r["side"],
            r["our_probability"], r["market_probability"], r["edge"], r["action"],
            r["contract_count"], r["price_paid"], r["result"], r["pnl"],
        ))

    conn.commit()
    cur.close()
    conn.close()

    print(f"Inserted {len(rows)} rows into backtest_trades for run '{run_id}'.")

    # Summary
    bet_rows = [r for r in rows if r["action"] in ("BET_YES", "BET_NO")]
    wins = sum(1 for r in bet_rows if r["pnl"] is not None and r["pnl"] > 0)
    total_pnl = sum(r["pnl"] for r in bet_rows if r["pnl"] is not None)

    print(f"\nSummary — {run_id}:")
    print(f"  Total signals evaluated:  {len(rows)}")
    print(f"  Bets simulated:           {len(bet_rows)}")
    if bet_rows:
        print(f"  Win rate:                 {wins}/{len(bet_rows)} ({100*wins/len(bet_rows):.0f}%)")
        print(f"  Simulated P&L:            ${total_pnl:+.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lakshmera backtest runner")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end",   required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--run-id", required=True, help="Unique label for this run")
    args = parser.parse_args()

    run_backtest(
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        args.run_id,
    )
