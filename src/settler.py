"""
Checks all unsettled trades in the DB against the Kalshi API.
When a market has resolved, records the result and calculates P&L.

P&L logic:
  Each Kalshi contract pays $1.00 if your side wins.
  You spent `price_paid` per contract.
  win:  pnl = contract_count * (1.00 - price_paid)
  lose: pnl = -contract_count * price_paid  (≈ -amount_usd)
"""

from database import get_connection
from kalshi_client import KalshiClient


def settle_trades():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ticker, side, amount_usd, contract_count, price_paid, market_probability
        FROM trades
        WHERE settled = FALSE
        ORDER BY created_at
        """
    )
    unsettled = cur.fetchall()

    if not unsettled:
        print("Settlement check: no unsettled trades.")
        cur.close()
        conn.close()
        return

    print(f"Settlement check: {len(unsettled)} unsettled trade(s)...")
    client = KalshiClient()
    settled_count = 0

    for row in unsettled:
        trade_id, ticker, side, amount_usd, contract_count, price_paid, market_prob = row

        try:
            market = client.get_market(ticker)
        except Exception as e:
            print(f"  {ticker}: API error — {e}")
            continue

        result = market.get("result", "")
        if result not in ("yes", "no"):
            continue  # Market not resolved yet

        # Derive price_paid for trades logged before this column was added
        if price_paid is None:
            price_paid = float(market_prob) if side == "yes" else (1.0 - float(market_prob))

        price_paid = float(price_paid)
        amount_usd = float(amount_usd)

        # Derive contract_count for legacy trades
        if contract_count is None:
            contract_count = max(1, round(amount_usd / price_paid))

        contract_count = int(contract_count)

        if result == side:
            pnl = round(contract_count * (1.0 - price_paid), 2)
        else:
            pnl = round(-contract_count * price_paid, 2)

        cur.execute(
            "UPDATE trades SET settled=TRUE, result=%s, pnl=%s WHERE id=%s",
            (result, pnl, trade_id),
        )
        settled_count += 1
        outcome = "WON" if result == side else "LOST"
        print(f"  {ticker}: {outcome} ({side.upper()} @ {price_paid:.2f}) | pnl ${pnl:+.2f}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Settlement complete: {settled_count} trade(s) settled.\n")
