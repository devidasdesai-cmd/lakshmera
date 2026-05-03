from collections import defaultdict
from datetime import date, timedelta

from config import (
    PAPER_TRADING,
    STARTING_CAPITAL,
    MAX_TRADE_SIZE_USD,
    DAILY_LOSS_LIMIT_USD,
    MIN_EDGE_THRESHOLD,
    MAX_EDGE_THRESHOLD,
    FORECAST_HORIZON_DAYS,
    KELLY_CAP,
    TARGET_SERIES,
)
from kalshi_client import KalshiClient
from market_parser import parse_market
from model import calculate_edge, kelly_size
from weather import get_ensemble_temps, probability_above, probability_below, probability_between
from database import log_signal, log_trade, get_daily_realized_loss, get_open_tickers
from settler import settle_trades


def _estimate(temps, direction, threshold_f, low_f, high_f):
    if direction == "above":
        return probability_above(temps, threshold_f)
    elif direction == "below":
        return probability_below(temps, threshold_f)
    elif direction == "bucket" and low_f is not None and high_f is not None:
        return probability_between(temps, low_f, high_f)
    return None


def run_cycle():
    print(f"\n{'='*60}")
    print(f"LAKSHMERA WEATHER BOT — PAPER_TRADING={PAPER_TRADING}")
    print(f"{'='*60}\n")

    client = KalshiClient()

    if not PAPER_TRADING:
        daily_loss = get_daily_realized_loss()
        if daily_loss >= DAILY_LOSS_LIMIT_USD:
            print(f"Daily loss limit of ${DAILY_LOSS_LIMIT_USD} reached. Shutting down.")
            return

    # Fetch markets for each target weather series
    horizon_cutoff = date.today() + timedelta(days=FORECAST_HORIZON_DAYS)
    raw_markets = []
    for series_ticker in TARGET_SERIES:
        data = client.get_events(series_ticker=series_ticker)
        for event in data.get("events", []):
            for m in event.get("markets", []):
                raw_markets.append(m)

    print(f"Weather markets fetched: {len(raw_markets)}")

    today = date.today()
    actionable = []
    for m in raw_markets:
        parsed = parse_market(m)
        if parsed is None:
            continue
        # Skip today's contracts — weather is already happening and our
        # forecast model doesn't account for observations made so far today.
        if parsed["target_date"] <= today:
            continue
        if parsed["target_date"] > horizon_cutoff:
            continue
        actionable.append(parsed)

    print(f"Actionable markets within {FORECAST_HORIZON_DAYS}-day horizon: {len(actionable)}\n")

    # Load tickers we already hold so we don't double-bet the same contract
    open_tickers = get_open_tickers(paper_trade=PAPER_TRADING)
    print(f"Already holding positions on {len(open_tickers)} ticker(s) — will skip those.\n")

    # Pre-fetch ensemble data once per (city, date) — avoids redundant API calls
    # and prevents timeouts when many contracts share the same city+date.
    print("Pre-fetching ensemble forecast data...")
    ensemble_cache: dict[tuple, list[float]] = {}
    city_dates = {(m["city"]["name"], m["target_date"]): m["city"] for m in actionable}
    for (city_name, target_date), city in city_dates.items():
        temps = get_ensemble_temps(city["lat"], city["lon"], target_date, city["tz"])
        ensemble_cache[(city_name, target_date)] = temps
        if temps:
            mean = sum(temps) / len(temps)
            print(f"  {city_name} {target_date}: {len(temps)} members | "
                  f"mean={mean:.1f}°F min={min(temps):.1f}°F max={max(temps):.1f}°F")
        else:
            print(f"  {city_name} {target_date}: no data")
    print()

    bets_placed = 0

    for market in actionable:
        city        = market["city"]
        ticker      = market["ticker"]
        target_date = market["target_date"]
        threshold_f = market["threshold_f"]
        direction   = market["direction"]
        low_f       = market["low_f"]
        high_f      = market["high_f"]
        yes_price   = market["yes_price"]

        if direction == "above":
            label = f">{threshold_f}°F"
        elif direction == "below":
            label = f"<{threshold_f}°F"
        else:
            label = f"{low_f}-{high_f}°F"

        print(f"Evaluating: {ticker}")
        print(f"  {city['name']} | {target_date} | high {label}")
        print(f"  Market YES price: {yes_price:.2f}")

        if ticker in open_tickers:
            print(f"  Skipping — already have an open position.\n")
            continue

        temps = ensemble_cache.get((city["name"], target_date))
        if not temps:
            print("  Skipping — no forecast data.\n")
            continue

        our_prob = _estimate(temps, direction, threshold_f, low_f, high_f)
        if our_prob is None:
            print("  Skipping — probability estimate failed.\n")
            continue

        edge = calculate_edge(our_prob, yes_price)
        print(f"  Our probability: {our_prob:.2f} | Edge: {edge:+.2f}")

        if abs(edge) < MIN_EDGE_THRESHOLD:
            action = "NO_BET"
            print(f"  Action: NO_BET (edge {abs(edge):.2f} < {MIN_EDGE_THRESHOLD})\n")
        elif abs(edge) > MAX_EDGE_THRESHOLD:
            action = "SUSPICIOUS_EDGE"
            print(f"  Action: SUSPICIOUS_EDGE (edge {abs(edge):.2f} > {MAX_EDGE_THRESHOLD} — possible GFS bias, skipping)\n")
        elif edge > 0:
            action = "BET_YES"
        else:
            action = "BET_NO"

        log_signal(city["name"], ticker, our_prob, yes_price, edge, action)

        if action in ("NO_BET", "SUSPICIOUS_EDGE"):
            continue

        bet_usd = min(kelly_size(abs(edge), STARTING_CAPITAL, KELLY_CAP), MAX_TRADE_SIZE_USD)
        bet_usd = max(round(bet_usd), 5)
        side = "yes" if action == "BET_YES" else "no"
        price = yes_price if side == "yes" else market["no_price"]
        contract_count = min(200, max(1, int((bet_usd * 100) / (price * 100))))

        if PAPER_TRADING:
            print(f"  [PAPER] {action}: {contract_count} contracts @ {price:.2f} (~${bet_usd})\n")
            log_trade(ticker, side, bet_usd, contract_count, price, our_prob, yes_price, paper_trade=True)
        else:
            price_cents = int(price * 100)
            print(f"  [LIVE] {action}: {contract_count} contracts @ {price_cents}¢ (~${bet_usd})")
            result = client.place_order(ticker, side, contract_count, price_cents)
            print(f"  Order result: {result}\n")
            log_trade(ticker, side, bet_usd, contract_count, price, our_prob, yes_price, paper_trade=False)

        bets_placed += 1

    print(f"\nCycle complete. Bets placed (or paper logged): {bets_placed}")

    # Check whether any previously placed bets have now settled
    settle_trades()
