from datetime import date, timedelta

from config import (
    PAPER_TRADING,
    STARTING_CAPITAL,
    MAX_TRADE_SIZE_USD,
    DAILY_LOSS_LIMIT_USD,
    MIN_EDGE_THRESHOLD,
    FORECAST_HORIZON_DAYS,
    KELLY_CAP,
    TARGET_SERIES,
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

    # Parse and filter to actionable markets within our horizon
    actionable = []
    for m in raw_markets:
        parsed = parse_market(m)
        if parsed is None:
            continue
        if parsed["target_date"] > horizon_cutoff:
            continue
        actionable.append(parsed)

    print(f"Actionable markets within {FORECAST_HORIZON_DAYS}-day horizon: {len(actionable)}\n")

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

        label = (
            f"{'>' if direction == 'above' else '<' if direction == 'below' else f'{low_f}-{high_f}'}"
            f"{threshold_f}°F"
        )
        print(f"Evaluating: {ticker}")
        print(f"  {city['name']} | {target_date} | high {label}")
        print(f"  Market YES price: {yes_price:.2f}")

        our_prob = estimate_probability(city, target_date, threshold_f, direction, low_f, high_f)
        if our_prob is None:
            print("  Skipping — no forecast data.\n")
            continue

        edge = calculate_edge(our_prob, yes_price)
        print(f"  Our probability: {our_prob:.2f} | Edge: {edge:+.2f}")

        if abs(edge) < MIN_EDGE_THRESHOLD:
            action = "NO_BET"
            print(f"  Action: NO_BET (edge {abs(edge):.2f} < {MIN_EDGE_THRESHOLD})\n")
        elif edge > 0:
            action = "BET_YES"
        else:
            action = "BET_NO"

        log_signal(city["name"], ticker, our_prob, yes_price, edge, action)

        if action == "NO_BET":
            continue

        bet_usd = min(kelly_size(abs(edge), STARTING_CAPITAL, KELLY_CAP), MAX_TRADE_SIZE_USD)
        bet_usd = max(round(bet_usd), 5)
        side = "yes" if action == "BET_YES" else "no"
        price = yes_price if side == "yes" else market["no_price"]
        contract_count = max(1, int((bet_usd * 100) / (price * 100)))

        if PAPER_TRADING:
            print(f"  [PAPER] {action}: {contract_count} contracts @ {price:.2f} (~${bet_usd})\n")
            log_trade(ticker, side, bet_usd, our_prob, yes_price, paper_trade=True)
        else:
            price_cents = int(price * 100)
            print(f"  [LIVE] {action}: {contract_count} contracts @ {price_cents}¢ (~${bet_usd})")
            result = client.place_order(ticker, side, contract_count, price_cents)
            print(f"  Order result: {result}\n")
            log_trade(ticker, side, bet_usd, our_prob, yes_price, paper_trade=False)

        bets_placed += 1

    print(f"\nCycle complete. Bets placed (or paper logged): {bets_placed}")
