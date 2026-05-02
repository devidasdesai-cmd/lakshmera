from datetime import date, timedelta

from config import (
    PAPER_TRADING,
    STARTING_CAPITAL,
    MAX_TRADE_SIZE_USD,
    DAILY_LOSS_LIMIT_USD,
    MIN_EDGE_THRESHOLD,
    FORECAST_HORIZON_DAYS,
    KELLY_CAP,
    TARGET_CITIES,
)
from kalshi_client import KalshiClient
from market_parser import parse_market
from model import estimate_probability, calculate_edge, kelly_size
from database import log_signal, log_trade, get_daily_realized_loss


def run_cycle():
    print(f"\n{'='*60}")
    print(f"LAKSHMERA WEATHER BOT — PAPER_TRADING={PAPER_TRADING}")
    print(f"{'='*60}\n")

    client = KalshiClient()

    # Check daily loss limit (only relevant in live mode)
    if not PAPER_TRADING:
        daily_loss = get_daily_realized_loss()
        if daily_loss >= DAILY_LOSS_LIMIT_USD:
            print(f"Daily loss limit of ${DAILY_LOSS_LIMIT_USD} reached. Shutting down.")
            return

    # Fetch only markets closing within our horizon window
    print("Fetching open markets from Kalshi...")
    all_markets = client.get_all_open_markets()
    print(f"Total open markets fetched: {len(all_markets)}")

    # Print 10 sample markets so we can see Kalshi's actual format
    print("\n--- SAMPLE MARKETS (first 10) ---")
    for m in all_markets[:10]:
        print(f"  ticker={m.get('ticker')} | title={m.get('title')} | subtitle={m.get('subtitle')}")
    print("--- END SAMPLE ---\n")

    # Also print any market whose ticker or title contains weather keywords
    keywords = ["temp", "weather", "rain", "snow", "wind", "high", "low", "precip", "storm", "KDFW", "KORD", "KJFK"]
    weather_samples = [
        m for m in all_markets
        if any(k.lower() in (m.get("ticker", "") + m.get("title", "")).lower() for k in keywords)
    ]
    print(f"--- WEATHER-RELATED MARKETS ({len(weather_samples)} found) ---")
    for m in weather_samples[:20]:
        print(f"  ticker={m.get('ticker')} | title={m.get('title')} | close={m.get('close_time')}")
    print("--- END WEATHER ---\n")

    # Filter to temperature markets resolving within our horizon
    horizon_cutoff = date.today() + timedelta(days=FORECAST_HORIZON_DAYS)
    actionable = []
    for m in all_markets:
        parsed = parse_market(m)
        if parsed is None:
            continue
        if parsed["target_date"] > horizon_cutoff:
            continue
        actionable.append(parsed)

    print(f"Temperature markets within {FORECAST_HORIZON_DAYS}-day horizon: {len(actionable)}\n")

    city_names = {c["name"] for c in TARGET_CITIES}
    bets_placed = 0

    for market in actionable:
        city = market["city"]
        if city["name"] not in city_names:
            continue

        ticker = market["ticker"]
        target_date = market["target_date"]
        threshold_f = market["threshold_f"]
        direction = market["direction"]
        yes_price = market["yes_price"]

        print(f"Evaluating: {ticker}")
        print(f"  {city['name']} | {target_date} | high {'above' if direction == 'above' else 'below'} {threshold_f}°F")
        print(f"  Market YES price: {yes_price:.2f} ({yes_price*100:.0f}¢)")

        # Get our probability estimate from the ensemble model
        our_prob = estimate_probability(city, target_date, threshold_f, direction)
        if our_prob is None:
            print("  Skipping — no forecast data.\n")
            continue

        market_prob = yes_price  # YES price = market-implied probability
        edge = calculate_edge(our_prob, market_prob)

        print(f"  Our probability: {our_prob:.2f} | Edge: {edge:+.2f}")

        # Determine action
        if abs(edge) < MIN_EDGE_THRESHOLD:
            action = "NO_BET"
            print(f"  Action: NO_BET (edge {abs(edge):.2f} < threshold {MIN_EDGE_THRESHOLD})\n")
        elif edge > 0:
            action = "BET_YES"
        else:
            action = "BET_NO"

        log_signal(city["name"], ticker, our_prob, market_prob, edge, action)

        if action == "NO_BET":
            continue

        # Size the bet using Kelly Criterion
        bet_usd = min(
            kelly_size(abs(edge), STARTING_CAPITAL, KELLY_CAP),
            MAX_TRADE_SIZE_USD,
        )
        # Round to nearest dollar, minimum $5
        bet_usd = max(round(bet_usd), 5)

        side = "yes" if action == "BET_YES" else "no"
        price_cents = int(market["yes_price"] * 100) if side == "yes" else int(market["no_price"] * 100)
        # Each Kalshi contract pays $1, so contract count ≈ bet_usd / price
        contract_count = max(1, int((bet_usd * 100) / price_cents))

        if PAPER_TRADING:
            print(f"  [PAPER] {action}: {contract_count} contracts @ {price_cents}¢ (~${bet_usd})\n")
            log_trade(ticker, side, bet_usd, our_prob, market_prob, paper_trade=True)
        else:
            print(f"  [LIVE]  {action}: {contract_count} contracts @ {price_cents}¢ (~${bet_usd})")
            result = client.place_order(ticker, side, contract_count, price_cents)
            print(f"  Order result: {result}\n")
            log_trade(ticker, side, bet_usd, our_prob, market_prob, paper_trade=False)

        bets_placed += 1

    print(f"\nCycle complete. Bets placed (or logged as paper): {bets_placed}")
