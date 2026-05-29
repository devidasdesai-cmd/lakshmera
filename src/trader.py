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
    MAX_YES_BET_MARKET_PRICE,
    BAN_TAIL_NO_BETS,
    ALLOW_CHEAP_TAIL_YES_THROUGH_SUSPICIOUS,
    CHEAP_TAIL_YES_MAX_PRICE,
    ALLOW_BUCKET_NO_IN_LEAN_YES_ZONE,
    LEAN_YES_ZONE_MIN,
    LEAN_YES_ZONE_MAX,
    REDUCED_STAKE_NO_CITIES,
    REDUCED_STAKE_NO_CAP_USD,
    ONE_BET_PER_CITY_DATE,
    USE_ECMWF_BLEND,
    USE_CLIMATOLOGY_BASE_RATE,
    LOG_NWS_FORECAST,
    LOG_ORDERBOOK,
    FORECAST_HORIZON_DAYS,
    KELLY_CAP,
    KALSHI_FEE_RATE,
    TARGET_SERIES,
)
from kalshi_client import KalshiClient
from market_parser import parse_market
from model import kelly_size, calibrate_probability, compute_stake_cap
from weather import (
    get_ensemble_temps, get_blended_ensemble_temps,
    get_climatology_temps, climatology_base_rate,
    get_nws_forecast_temps,
    probability_above, probability_below, probability_between,
)
from database import log_signal, log_trade, get_daily_realized_loss, get_open_tickers
# settle_trades is now called upfront from main.py


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
    nws_cache:      dict[str, dict] = {}   # city_name → {date: forecast_temp}
    city_dates = {(m["city"]["name"], m["target_date"]): m["city"] for m in actionable}
    for (city_name, target_date), city in city_dates.items():
        if USE_ECMWF_BLEND:
            temps = get_blended_ensemble_temps(city["lat"], city["lon"], target_date, city["tz"])
        else:
            temps = get_ensemble_temps(city["lat"], city["lon"], target_date, city["tz"])
        ensemble_cache[(city_name, target_date)] = temps
        if temps:
            mean = sum(temps) / len(temps)
            print(f"  {city_name} {target_date}: {len(temps)} members | "
                  f"mean={mean:.1f}°F min={min(temps):.1f}°F max={max(temps):.1f}°F")
        else:
            print(f"  {city_name} {target_date}: no data")

    # Pre-fetch NWS forecasts (one call per city; covers all dates in the forecast horizon).
    if LOG_NWS_FORECAST:
        print("\nPre-fetching NWS local forecasts (NBM-derived)...")
        seen_cities = {m["city"]["name"]: m["city"] for m in actionable}
        for city_name, city in seen_cities.items():
            nws_cache[city_name] = get_nws_forecast_temps(city["lat"], city["lon"])
            if nws_cache[city_name]:
                # Show a short summary of upcoming forecast for this city
                upcoming = sorted(nws_cache[city_name].items())[:4]
                summary = ", ".join(f"{d.strftime('%m/%d')}:{t:.0f}°F" for d, t in upcoming)
                print(f"  {city_name}: {summary}")
            else:
                print(f"  {city_name}: NWS forecast unavailable")
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

        # Climatology base rate: city- and date-specific historical exceedance rate, used
        # as the shrinkage anchor for calibration. Falls back to global default if unavailable.
        base_rate = None
        if USE_CLIMATOLOGY_BASE_RATE:
            clim_temps = get_climatology_temps(city["lat"], city["lon"], target_date, city["tz"])
            base_rate = climatology_base_rate(clim_temps, threshold_f, direction, low_f, high_f)
            if base_rate is not None:
                print(f"  Climatology base rate: {base_rate*100:.0f}% (from {len(clim_temps)} historical days)")

        our_prob = calibrate_probability(raw_prob, base_rate=base_rate)

        # NWS forecast sanity check (informational; not used in math)
        if LOG_NWS_FORECAST:
            nws_forecasts = nws_cache.get(city["name"], {})
            nws_temp = nws_forecasts.get(target_date)
            if nws_temp is not None:
                # Mean of our blended ensemble for comparison
                model_mean = sum(temps) / len(temps) if temps else None
                if model_mean is not None:
                    diff = nws_temp - model_mean
                    flag = " ⚠" if abs(diff) >= 4 else ""
                    print(f"  NWS forecast: {nws_temp:.0f}°F vs our model mean {model_mean:.1f}°F (diff {diff:+.1f}°F){flag}")

        yes_fee  = KALSHI_FEE_RATE * (1 - yes_ask)
        no_fee   = KALSHI_FEE_RATE * (1 - no_ask)
        edge_yes = our_prob - yes_ask - yes_fee
        edge_no  = (1 - our_prob) - no_ask - no_fee

        print(f"  Our prob: raw {raw_prob:.2f} → calibrated {our_prob:.2f} | Edge YES: {edge_yes:+.2f}  Edge NO: {edge_no:+.2f}")

        reason = None
        if edge_yes > MAX_EDGE_THRESHOLD or edge_no > MAX_EDGE_THRESHOLD:
            # Priority 3: allow cheap tail YES bets through the "suspicious" cap.
            # Asymmetric-payoff longshots (e.g., Phoenix > 105°F at 3¢) — capped
            # downside ($100 max loss) but huge upside on rare wins.
            is_cheap_tail_yes = (
                ALLOW_CHEAP_TAIL_YES_THROUGH_SUSPICIOUS
                and edge_yes > MAX_EDGE_THRESHOLD
                and direction in ("above", "below")
                and yes_ask <= CHEAP_TAIL_YES_MAX_PRICE
            )
            if is_cheap_tail_yes:
                action = "BET_YES"
                reason = "cheap_tail_yes_allowed_through_suspicious_edge"
                print(f"  Action: BET_YES (cheap tail YES at {yes_ask:.2f} ≤ {CHEAP_TAIL_YES_MAX_PRICE} — "
                      f"allowed through MAX_EDGE_THRESHOLD as asymmetric-payoff longshot)\n")
            else:
                action = "SUSPICIOUS_EDGE"
                reason = "suspicious_edge_max_exceeded"
                print(f"  Action: SUSPICIOUS_EDGE (edge exceeds {MAX_EDGE_THRESHOLD} — possible GFS bias, skipping)\n")
        elif edge_yes > MIN_EDGE_THRESHOLD:
            if direction == "bucket":
                action = "NO_BET"
                reason = "bucket_yes_banned"
                print(f"  Action: NO_BET (YES edge {edge_yes:+.2f} but bucket contract — GFS too imprecise for 2°F ranges)\n")
            elif yes_ask > MAX_YES_BET_MARKET_PRICE:
                # Priority 2: don't bet YES when market already prices YES above 20%.
                # Historical data: 20-50% market YES is a losing zone for YES bets.
                action = "NO_BET"
                reason = "yes_market_price_too_high"
                print(f"  Action: NO_BET (YES edge {edge_yes:+.2f} but market YES price {yes_ask:.2f} > {MAX_YES_BET_MARKET_PRICE} cap)\n")
            else:
                action = "BET_YES"
        elif edge_no > MIN_EDGE_THRESHOLD:
            # Lean-YES bucket NO carve-out (added 2026-05-25). Bucket NO blocks in
            # 50-65% mkt YES band ran 8/10 (80% WR, +$589) over May 14-23. Allow
            # through the MAX_NO_BET_YES_PRICE cap to gather forward data.
            is_lean_yes_bucket_no = (
                ALLOW_BUCKET_NO_IN_LEAN_YES_ZONE
                and direction == "bucket"
                and LEAN_YES_ZONE_MIN <= yes_ask < LEAN_YES_ZONE_MAX
            )
            if yes_ask > MAX_NO_BET_YES_PRICE and not is_lean_yes_bucket_no:
                action = "NO_BET"
                reason = "yes_price_too_high"
                print(f"  Action: NO_BET (NO edge {edge_no:+.2f} but YES price {yes_ask:.2f} > {MAX_NO_BET_YES_PRICE} cap)\n")
            elif BAN_TAIL_NO_BETS and direction in ("above", "below"):
                # Priority 1: ban Tail NO bets. Historical: -$658 across 38 trades at 65.8% WR —
                # the bet structure requires ~70%+ WR to break even, model can't reliably hit it.
                action = "NO_BET"
                reason = "tail_no_banned"
                print(f"  Action: NO_BET (NO edge {edge_no:+.2f} but tail contract — Tail NO bets banned, "
                      f"historically -$658 P&L)\n")
            else:
                action = "BET_NO"
                if is_lean_yes_bucket_no:
                    reason = "lean_yes_bucket_no_carveout"
                    print(f"  Action: BET_NO (lean-YES bucket NO carve-out: mkt YES {yes_ask:.2f} in "
                          f"[{LEAN_YES_ZONE_MIN}, {LEAN_YES_ZONE_MAX}), bypassing {MAX_NO_BET_YES_PRICE} cap)\n")
        else:
            action = "NO_BET"
            reason = "edge_too_low"
            print(f"  Action: NO_BET (best edge {max(edge_yes, edge_no):.2f} < {MIN_EDGE_THRESHOLD})\n")

        log_signal(city["name"], ticker, our_prob, yes_ask, edge_yes, action, reason=reason)

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

        side = "yes" if action == "BET_YES" else "no"
        price = yes_ask if side == "yes" else no_ask
        # Priority 5: tier-based stake cap. Higher caps for historically profitable categories.
        tier_cap = compute_stake_cap(side, market["direction"], price)
        # Reduced-stake cities for NO bets (2026-05-28 P&L audit). Apply after tier cap.
        if side == "no" and market["city"]["name"] in REDUCED_STAKE_NO_CITIES:
            tier_cap = min(tier_cap, REDUCED_STAKE_NO_CAP_USD)
        bet_usd = min(kelly_size(active_edge, STARTING_CAPITAL, KELLY_CAP), tier_cap, MAX_TRADE_SIZE_USD)
        bet_usd = max(round(bet_usd), 5)
        contract_count = min(200, max(1, int((bet_usd * 100) / (price * 100))))

        # Diagnostic: log Kalshi order book depth at the ask. In paper mode this is
        # informational only — for live trading we'd use this to verify our bet size
        # is fillable at the quoted price.
        if LOG_ORDERBOOK:
            try:
                ask_price, available = client.get_liquidity_at_ask(ticker, side)
                if ask_price is not None:
                    fillable = "✓" if available >= contract_count else "⚠ partial"
                    slippage = ask_price - price
                    slip_note = f", slippage {slippage:+.3f}" if abs(slippage) > 0.001 else ""
                    print(f"  Order book: best ask ${ask_price:.3f}, {int(available)} contracts available "
                          f"({fillable} for our {contract_count}{slip_note})")
                else:
                    print(f"  Order book: no liquidity on {side.upper()} side")
            except Exception as e:
                print(f"  Order book lookup failed: {e}")

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
    # Note: settlement now runs upfront in main.py so it completes even if
    # this trading phase is killed by a runner timeout.
