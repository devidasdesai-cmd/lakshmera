from __future__ import annotations

from datetime import date, datetime, timezone

from config import (
    PAPER_TRADING,
    STARTING_CAPITAL,
    MAX_TRADE_SIZE_USD,
    MIN_EDGE_THRESHOLD,
    MAX_EDGE_THRESHOLD,
    MAX_NO_BET_YES_PRICE,
    ONE_BET_PER_CITY_DATE,
    KELLY_CAP,
    KALSHI_FEE_RATE,
    RAIN_TARGET_SERIES,
    RAIN_MAX_ENTRY_DAY,
)
from kalshi_client import KalshiClient
from rain_parser import parse_rain_market
from model import kelly_size
from weather import get_monthly_actual_precip, get_ensemble_precip_remaining, probability_precip_above
from database import log_signal, log_trade, get_open_tickers, get_rain_cities_bet_today
# settle_trades is now called upfront from main.py


def _current_gfs_run() -> str:
    hour = datetime.now(timezone.utc).hour
    gfs_cycle = ((hour - 4) % 24 // 6) * 6
    return f"{gfs_cycle:02d}z"


def run_rain_cycle():
    today = date.today()

    # After day 10 we're in "signals-only" mode: still evaluate markets and log
    # what we *would* have bet, but skip the actual trade placement. This gives
    # us data to retrospectively analyze whether late-month rain bets would
    # have been profitable, so we can revisit RAIN_MAX_ENTRY_DAY in the future.
    past_entry_cutoff = today.day > RAIN_MAX_ENTRY_DAY

    gfs_run = f"rain_{_current_gfs_run()}"

    print(f"\n{'='*60}")
    mode = "SIGNALS ONLY (past day-10 cutoff)" if past_entry_cutoff else "ACTIVE"
    print(f"RAIN MARKETS — PAPER_TRADING={PAPER_TRADING} | {gfs_run} | Day {today.day} of month | Mode: {mode}")
    print(f"{'='*60}\n")

    client = KalshiClient()

    raw_markets = []
    for series_ticker in RAIN_TARGET_SERIES:
        data = client.get_events(series_ticker=series_ticker)
        for event in data.get("events", []):
            for m in event.get("markets", []):
                raw_markets.append(m)

    print(f"Rain markets fetched: {len(raw_markets)}")

    open_tickers = get_open_tickers(paper_trade=PAPER_TRADING)

    # To prevent multiple bets on the same city within a single day's cron cycles
    # (the original bug: each run picked the next-best threshold on the same city),
    # skip cities where we already placed a bet today. But ALLOW new bets on a city
    # on a different day, since forecasts and actuals genuinely change over a month.
    cities_bet_today = get_rain_cities_bet_today(paper_trade=PAPER_TRADING)
    if cities_bet_today:
        print(f"Already placed a rain bet today on {len(cities_bet_today)} cities — those are skipped: {sorted(cities_bet_today)}")

    actionable = []
    skipped_same_day = 0
    skipped_same_ticker = 0
    for m in raw_markets:
        parsed = parse_rain_market(m)
        if parsed is None:
            continue
        if parsed["year"] != today.year or parsed["month"] != today.month:
            continue
        # Same exact contract already open — always skip
        if parsed["ticker"] in open_tickers:
            skipped_same_ticker += 1
            continue
        # Different threshold on a city we already bet on today — skip
        series = parsed["ticker"].split('-')[0]
        if series in cities_bet_today:
            skipped_same_day += 1
            continue
        actionable.append(parsed)

    print(f"Actionable rain markets this month: {len(actionable)} "
          f"({skipped_same_ticker} already-open, {skipped_same_day} same-day on same city)\n")

    if not actionable:
        print("No actionable rain markets found.")
        return

    # Pre-fetch precipitation data once per city
    print("Pre-fetching precipitation data...")
    precip_cache: dict[str, tuple[float, list[float]]] = {}
    seen_cities = {m["city"]["name"]: m for m in actionable}
    for city_name, market in seen_cities.items():
        city = market["city"]
        actual = get_monthly_actual_precip(city["lat"], city["lon"], today.year, today.month, city["tz"])
        members = get_ensemble_precip_remaining(city["lat"], city["lon"], market["month_end"], city["tz"])
        precip_cache[city_name] = (actual, members)
        if members:
            totals = [actual + m for m in members]
            print(f"  {city_name}: {actual:.2f}\" so far | "
                  f"forecast month total: {sum(totals)/len(totals):.2f}\" mean "
                  f"({min(totals):.2f}\"–{max(totals):.2f}\")")
        else:
            print(f"  {city_name}: {actual:.2f}\" so far | no ensemble data")
    print()

    # ── Phase 1: Evaluate every rain market, log signals, collect bet candidates ──
    # Note: rain markets use raw probabilities — no calibration applied yet because
    # we have zero settled rain trades. Add a separate calibration once data is in.
    bet_candidates = []

    for market in actionable:
        city      = market["city"]
        ticker    = market["ticker"]
        threshold = market["threshold_inches"]
        yes_ask   = market["yes_ask"]
        no_ask    = market["no_ask"]

        print(f"Evaluating: {ticker}")
        print(f"  {city['name']} | month total > {threshold}\" | YES ask: {yes_ask:.2f}  NO ask: {no_ask:.2f}")

        if ticker in open_tickers:
            print(f"  Skipping — already have an open position.\n")
            continue

        actual_so_far, member_totals = precip_cache.get(city["name"], (0.0, []))
        our_prob = probability_precip_above(actual_so_far, member_totals, threshold)
        if our_prob is None:
            print("  Skipping — no forecast data.\n")
            continue

        yes_fee  = KALSHI_FEE_RATE * (1 - yes_ask)
        no_fee   = KALSHI_FEE_RATE * (1 - no_ask)
        edge_yes = our_prob - yes_ask - yes_fee
        edge_no  = (1 - our_prob) - no_ask - no_fee

        print(f"  Our prob: {our_prob:.2f} | Edge YES: {edge_yes:+.2f}  Edge NO: {edge_no:+.2f}")

        if edge_yes > MAX_EDGE_THRESHOLD or edge_no > MAX_EDGE_THRESHOLD:
            action = "SUSPICIOUS_EDGE"
            print(f"  Action: SUSPICIOUS_EDGE (edge > {MAX_EDGE_THRESHOLD} — possible model bias, skipping)\n")
        elif edge_yes > MIN_EDGE_THRESHOLD:
            action = "BET_YES"
        elif edge_no > MIN_EDGE_THRESHOLD:
            if yes_ask > MAX_NO_BET_YES_PRICE:
                action = "NO_BET"
                print(f"  Action: NO_BET (NO edge {edge_no:+.2f} but YES price {yes_ask:.2f} > {MAX_NO_BET_YES_PRICE} cap)\n")
            else:
                action = "BET_NO"
        else:
            action = "NO_BET"
            print(f"  Action: NO_BET (best edge {max(edge_yes, edge_no):.2f} < {MIN_EDGE_THRESHOLD})\n")

        log_signal(city["name"], ticker, our_prob, yes_ask, max(edge_yes, edge_no), action)

        if action in ("NO_BET", "SUSPICIOUS_EDGE"):
            continue

        active_edge = edge_yes if action == "BET_YES" else edge_no
        bet_candidates.append({
            'market':      market,
            'action':      action,
            'active_edge': active_edge,
            'our_prob':    our_prob,
            'yes_ask':     yes_ask,
            'no_ask':      no_ask,
        })

    # ── Phase 2: One bet per city — multiple thresholds on the same city's monthly
    # rain are correlated outcomes (if Dallas gets 4", then >2", >3" both win) ──
    if ONE_BET_PER_CITY_DATE:
        best_by_city = {}
        for c in bet_candidates:
            key = c['market']['city']['name']
            if key not in best_by_city or c['active_edge'] > best_by_city[key]['active_edge']:
                best_by_city[key] = c
        skipped = len(bet_candidates) - len(best_by_city)
        if skipped > 0:
            print(f"\nCorrelated bet filter: {len(bet_candidates)} candidates → {len(best_by_city)} kept "
                  f"({skipped} skipped — only the highest-edge bet per city is placed)\n")
        final_bets = list(best_by_city.values())
    else:
        final_bets = bet_candidates

    # ── Phase 3: Place trades (skipped after day-10 cutoff) ──
    if past_entry_cutoff:
        if final_bets:
            print(f"\n[SIGNALS-ONLY MODE] Would have placed {len(final_bets)} rain bet(s); "
                  f"skipping trade placement due to day-{RAIN_MAX_ENTRY_DAY} cutoff. "
                  f"Signals are logged in the database for retrospective analysis.")
        else:
            print(f"\n[SIGNALS-ONLY MODE] No actionable rain bets this run (also past day-{RAIN_MAX_ENTRY_DAY} cutoff).")
        print(f"\nRain cycle complete. Bets placed: 0 (signals-only mode)")
        return

    bets_placed = 0
    for c in final_bets:
        market      = c['market']
        action      = c['action']
        active_edge = c['active_edge']
        our_prob    = c['our_prob']
        yes_ask     = c['yes_ask']
        no_ask      = c['no_ask']
        ticker      = market['ticker']

        bet_usd = min(kelly_size(active_edge, STARTING_CAPITAL, KELLY_CAP), MAX_TRADE_SIZE_USD)
        bet_usd = max(round(bet_usd), 5)
        side = "yes" if action == "BET_YES" else "no"
        price = yes_ask if side == "yes" else no_ask
        contract_count = min(200, max(1, int((bet_usd * 100) / (price * 100))))

        if PAPER_TRADING:
            print(f"  [PAPER] {ticker} {action}: {contract_count} contracts @ {price:.2f} (~${bet_usd})")
            log_trade(ticker, side, bet_usd, contract_count, price, our_prob, yes_ask,
                      paper_trade=True, gfs_run=gfs_run)
        else:
            price_cents = int(price * 100)
            print(f"  [LIVE] {ticker} {action}: {contract_count} contracts @ {price_cents}¢ (~${bet_usd})")
            result = client.place_order(ticker, side, contract_count, price_cents)
            print(f"  Order result: {result}")
            log_trade(ticker, side, bet_usd, contract_count, price, our_prob, yes_ask,
                      paper_trade=False, gfs_run=gfs_run)

        bets_placed += 1

    print(f"\nRain cycle complete. Bets placed: {bets_placed}")
    # Note: settlement runs upfront in main.py (covers both temp and rain trades).
