from collections import defaultdict
from datetime import date, timedelta, datetime, timezone

from config import (
    PAPER_TRADING,
    STARTING_CAPITAL,
    MAX_TRADE_SIZE_USD,
    DAILY_LOSS_LIMIT_USD,
    MIN_EDGE_THRESHOLD,
    MAX_EDGE_THRESHOLD,
    MAX_NO_BET_YES_PRICE,
    MAX_NO_BET_OUR_PROB,
    ONE_BET_PER_CITY_DATE,
    FORECAST_HORIZON_DAYS,
    KELLY_CAP,
    KALSHI_FEE_RATE,
    TARGET_SERIES,
)
from kalshi_client import KalshiClient
from market_parser import parse_market
from model import kelly_size, calibrate_probability
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


def _current_gfs_run() -> str:
    """
    Returns the GFS cycle that was used this run (e.g. '06z').
    GFS publishes at 00/06/12/18z UTC. Open-Meteo takes ~4h to process,
    so we subtract 4h from current UTC time to identify the source cycle.
    """
    hour = datetime.now(timezone.utc).hour
    gfs_cycle = ((hour - 4) % 24 // 6) * 6
    return f"{gfs_cycle:02d}z"


def run_cycle():
    gfs_run = _current_gfs_run()

    print(f"\n{'='*60}")
    print(f"LAKSHMERA WEATHER BOT — PAPER_TRADING={PAPER_TRADING} | GFS run: {gfs_run}")
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
    # 18z run fires at 22 UTC (5pm CT) — tomorrow's contracts are already efficiently
    # priced by this point. Focus on 2+ days out where the late-day forecast is still
    # genuinely new information for the market.
    min_target_date = today + timedelta(days=2 if gfs_run == "18z" else 1)

    actionable = []
    for m in raw_markets:
        parsed = parse_market(m)
        if parsed is None:
            continue
        if parsed["target_date"] < min_target_date:
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

    # ── Phase 1: Evaluate every market, log signals, collect bet candidates ──
    bet_candidates = []

    for market in actionable:
        city        = market["city"]
        ticker      = market["ticker"]
        target_date = market["target_date"]
        threshold_f = market["threshold_f"]
        direction   = market["direction"]
        low_f       = market["low_f"]
        high_f      = market["high_f"]
        yes_ask     = market["yes_ask"]
        no_ask      = market["no_ask"]

        if direction == "above":
            label = f">{threshold_f}°F"
        elif direction == "below":
            label = f"<{threshold_f}°F"
        else:
            label = f"{low_f}-{high_f}°F"

        print(f"Evaluating: {ticker}")
        print(f"  {city['name']} | {target_date} | high {label}")
        print(f"  YES ask: {yes_ask:.2f}  NO ask: {no_ask:.2f}")

        if ticker in open_tickers:
            print(f"  Skipping — already have an open position.\n")
            continue

        temps = ensemble_cache.get((city["name"], target_date))
        if not temps:
            print("  Skipping — no forecast data.\n")
            continue

        raw_prob = _estimate(temps, direction, threshold_f, low_f, high_f)
        if raw_prob is None:
            print("  Skipping — probability estimate failed.\n")
            continue

        # Apply calibration: GFS-derived probabilities are systematically miscalibrated.
        # We log both raw and calibrated for transparency; downstream uses calibrated.
        our_prob = calibrate_probability(raw_prob)

        yes_fee  = KALSHI_FEE_RATE * (1 - yes_ask)
        no_fee   = KALSHI_FEE_RATE * (1 - no_ask)
        edge_yes = our_prob - yes_ask - yes_fee
        edge_no  = (1 - our_prob) - no_ask - no_fee

        print(f"  Our prob: raw {raw_prob:.2f} → calibrated {our_prob:.2f} | Edge YES: {edge_yes:+.2f}  Edge NO: {edge_no:+.2f}")

        if edge_yes > MAX_EDGE_THRESHOLD or edge_no > MAX_EDGE_THRESHOLD:
            action = "SUSPICIOUS_EDGE"
            print(f"  Action: SUSPICIOUS_EDGE (edge exceeds {MAX_EDGE_THRESHOLD} — possible GFS bias, skipping)\n")
        elif edge_yes > MIN_EDGE_THRESHOLD:
            if direction == "bucket":
                action = "NO_BET"
                print(f"  Action: NO_BET (YES edge {edge_yes:+.2f} but bucket contract — GFS too imprecise for 2°F ranges)\n")
            else:
                action = "BET_YES"
        elif edge_no > MIN_EDGE_THRESHOLD:
            if yes_ask > MAX_NO_BET_YES_PRICE:
                action = "NO_BET"
                print(f"  Action: NO_BET (NO edge {edge_no:+.2f} but YES price {yes_ask:.2f} > {MAX_NO_BET_YES_PRICE} cap)\n")
            elif our_prob > MAX_NO_BET_OUR_PROB:
                action = "NO_BET"
                print(f"  Action: NO_BET (NO edge {edge_no:+.2f} but our prob {our_prob:.2f} > {MAX_NO_BET_OUR_PROB} threshold)\n")
            else:
                action = "BET_NO"
        else:
            action = "NO_BET"
            print(f"  Action: NO_BET (best edge {max(edge_yes, edge_no):.2f} < {MIN_EDGE_THRESHOLD})\n")

        log_signal(city["name"], ticker, our_prob, yes_ask, edge_yes, action)

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

    # ── Phase 2: Filter to one bet per (city, target_date) — highest edge wins ──
    # Multiple contracts on the same city+date resolve based on the same underlying
    # outcome (the day's high temperature), so they're correlated. Picking the single
    # highest-edge contract reduces variance without sacrificing expected value.
    if ONE_BET_PER_CITY_DATE:
        best_by_group = {}
        for c in bet_candidates:
            key = (c['market']['city']['name'], c['market']['target_date'])
            if key not in best_by_group or c['active_edge'] > best_by_group[key]['active_edge']:
                best_by_group[key] = c
        skipped = len(bet_candidates) - len(best_by_group)
        if skipped > 0:
            print(f"\nCorrelated bet filter: {len(bet_candidates)} candidates → {len(best_by_group)} kept "
                  f"({skipped} skipped — only the highest-edge bet per (city, date) is placed)\n")
        final_bets = list(best_by_group.values())
    else:
        final_bets = bet_candidates

    # ── Phase 3: Place trades ──
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
            log_trade(ticker, side, bet_usd, contract_count, price, our_prob, yes_ask, paper_trade=True, gfs_run=gfs_run)
        else:
            price_cents = int(price * 100)
            print(f"  [LIVE] {ticker} {action}: {contract_count} contracts @ {price_cents}¢ (~${bet_usd})")
            result = client.place_order(ticker, side, contract_count, price_cents)
            print(f"  Order result: {result}")
            log_trade(ticker, side, bet_usd, contract_count, price, our_prob, yes_ask, paper_trade=False, gfs_run=gfs_run)

        bets_placed += 1

    print(f"\nCycle complete. Bets placed (or paper logged): {bets_placed}")

    # Check whether any previously placed bets have now settled
    settle_trades()
