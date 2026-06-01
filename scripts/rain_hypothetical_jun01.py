"""
Hypothetical P&L analysis for May 11-31 rain BET signals that were blocked
by the RAIN_MAX_ENTRY_DAY=10 cutoff.

Question: if the bot had placed those bets, would May rain trading be
profitable enough to justify removing the cutoff?

Approach:
  1. Pull all rain BET_YES / BET_NO signals from May 11-31 with reason =
     'past_entry_cutoff_signals_only'.
  2. For each unique ticker, take the FIRST signal (the bot would have placed
     a bet at that point, then dedup'd subsequent runs via open_tickers).
  3. Apply the same one-bet-per-city-per-day rule: pick highest-edge per
     (city, date) — same as rain_trader.py Phase 2.
  4. Simulate stake sizing (kelly_size capped at $100, contract count cap 200).
  5. Look up actual settlement from Kalshi.
  6. Compute hypothetical P&L per trade and aggregate.
"""
from __future__ import annotations
import os, sys, time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
from kalshi_client import KalshiClient
from model import kelly_size
from config import STARTING_CAPITAL, MAX_RAIN_BET_SIZE_USD, KELLY_CAP, KALSHI_FEE_RATE


def conn():
    return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def parse_city(ticker: str) -> str:
    series = ticker.split("-")[0]
    M = {
        "KXRAINDALM":"Dallas","KXRAINHOUM":"Houston","KXRAINCHIM":"Chicago",
        "KXRAINSEAM":"Seattle","KXRAINLAXM":"Los Angeles","KXRAINSFOM":"San Francisco",
        "KXRAINMIAM":"Miami","KXRAINNYCM":"New York","KXRAINDENM":"Denver",
        "KXRAINAUSM":"Austin","KXRAINNO":"New Orleans",
    }
    return M.get(series, series)


def fetch_blocked_signals():
    """First BET signal per ticker, May 11-31, blocked by day-10 cutoff."""
    c = conn(); cur = c.cursor()
    cur.execute("""
      SELECT DISTINCT ON (ticker)
        ticker, city, our_probability::float, market_probability::float,
        edge::float, action, created_at::date AS d
      FROM signals
      WHERE ticker LIKE 'KXRAIN%'
        AND created_at >= '2026-05-11' AND created_at < '2026-06-01'
        AND action IN ('BET_YES', 'BET_NO')
        AND reason = 'past_entry_cutoff_signals_only'
      ORDER BY ticker, created_at ASC
    """)
    rows = cur.fetchall()
    cur.close(); c.close()
    return rows


def apply_one_per_city_per_day(rows):
    """Mirror rain_trader.py Phase 2: keep highest-edge candidate per (city, day)."""
    grouped = {}
    for tk, ci, op, mp, edge, action, d in rows:
        key = (ci, d)
        if key not in grouped or abs(edge) > abs(grouped[key][4]):
            grouped[key] = (tk, ci, op, mp, edge, action, d)
    return list(grouped.values())


def fetch_settlement(client, ticker, cache):
    if ticker in cache:
        return cache[ticker]
    try:
        mkt = client.get_market(ticker)
        result = (mkt.get("result") or "").lower() or None
    except Exception as e:
        result = None
    cache[ticker] = result
    return result


def simulate_stake(action, our_prob, market_prob):
    """Replicate rain_trader.py stake sizing."""
    yes_ask = market_prob
    no_ask = 1.0 - market_prob
    yes_fee = KALSHI_FEE_RATE * (1 - yes_ask)
    no_fee  = KALSHI_FEE_RATE * (1 - no_ask)
    edge_yes = our_prob - yes_ask - yes_fee
    edge_no  = (1 - our_prob) - no_ask - no_fee
    active_edge = edge_yes if action == "BET_YES" else edge_no
    bet_usd = min(kelly_size(active_edge, STARTING_CAPITAL, KELLY_CAP), MAX_RAIN_BET_SIZE_USD)
    bet_usd = max(round(bet_usd), 5)
    return bet_usd, edge_yes, edge_no


def simulate_pnl(action, market_prob, settle_result, bet_usd):
    """Compute hypothetical P&L given the bet."""
    price = market_prob if action == "BET_YES" else (1.0 - market_prob)
    price = max(0.01, min(0.99, price))
    contracts = min(200, max(1, int(bet_usd / price)))
    side = "yes" if action == "BET_YES" else "no"
    won = (settle_result == side)
    if won:
        return contracts * (1.0 - price) * (1.0 - KALSHI_FEE_RATE), contracts
    return -contracts * price, contracts


def main():
    print("Pulling blocked rain BET signals (May 11-31, past_entry_cutoff_signals_only)...")
    rows = fetch_blocked_signals()
    print(f"  {len(rows)} unique blocked-ticker candidates\n")

    print("Applying rain_trader Phase 2 (one bet per city per day, highest edge)...")
    rows = apply_one_per_city_per_day(rows)
    print(f"  After filter: {len(rows)} would-have-been-placed bets\n")

    print("Fetching actual settlements from Kalshi...")
    client = KalshiClient()
    cache = {}
    for r in rows:
        fetch_settlement(client, r[0], cache)
        time.sleep(0.05)
    resolved = sum(1 for v in cache.values() if v in ("yes", "no"))
    print(f"  Resolved: {resolved}/{len(rows)}\n")

    # Compute hypothetical P&L
    results = []
    for tk, ci, op, mp, edge, action, d in rows:
        settle = cache.get(tk)
        if settle not in ("yes", "no"):
            continue
        bet_usd, ey, en = simulate_stake(action, op, mp)
        pnl, contracts = simulate_pnl(action, mp, settle, bet_usd)
        results.append({
            "ticker": tk, "city": ci, "date": d, "action": action,
            "our_p": op, "mkt_p": mp, "edge": edge,
            "side_bet": "yes" if action == "BET_YES" else "no",
            "settle": settle, "stake": bet_usd, "contracts": contracts,
            "pnl": pnl, "won": settle == ("yes" if action == "BET_YES" else "no"),
        })

    # === Aggregate ===
    n = len(results)
    wins = sum(1 for r in results if r["won"])
    pnl_total = sum(r["pnl"] for r in results)
    stake_total = sum(r["stake"] for r in results)
    print("=" * 88)
    print(f"HYPOTHETICAL RAIN P&L — May 11-31 blocked signals")
    print("=" * 88)
    print(f"  Trades: {n}  Wins: {wins}  WR: {wins/n*100 if n else 0:.1f}%")
    print(f"  Total P&L: ${pnl_total:+.0f}  Total stake: ${stake_total:.0f}")
    print(f"  Avg P&L per trade: ${pnl_total/n if n else 0:+.2f}")
    print(f"  ROI on stake: {pnl_total/stake_total*100 if stake_total else 0:+.1f}%")

    # By side
    print("\n--- By side ---")
    for side in ("yes", "no"):
        sub = [r for r in results if r["side_bet"] == side]
        if not sub: continue
        n2 = len(sub); w2 = sum(1 for r in sub if r["won"]); p2 = sum(r["pnl"] for r in sub)
        s2 = sum(r["stake"] for r in sub)
        print(f"  {side.upper()} bets: N={n2:>3}  Wins={w2:>3}  WR={w2/n2*100:>5.1f}%  P&L=${p2:>+6.0f}  ROI={p2/s2*100 if s2 else 0:>+5.1f}%")

    # By city
    print("\n--- By city ---")
    by_city = defaultdict(list)
    for r in results: by_city[r["city"]].append(r)
    for ci, rs in sorted(by_city.items(), key=lambda kv: -sum(r["pnl"] for r in kv[1])):
        n2 = len(rs); w2 = sum(1 for r in rs if r["won"]); p2 = sum(r["pnl"] for r in rs)
        print(f"  {ci:<14} N={n2:>2}  Wins={w2:>2}  WR={w2/n2*100 if n2 else 0:>5.1f}%  P&L=${p2:>+6.0f}")

    # By week (calendar week of May)
    print("\n--- By week ---")
    by_week = defaultdict(list)
    for r in results:
        # Week 2 = May 11-17, Week 3 = May 18-24, Week 4 = May 25-31
        day = r["date"].day
        wk = "May 11-17" if day <= 17 else ("May 18-24" if day <= 24 else "May 25-31")
        by_week[wk].append(r)
    for wk in ("May 11-17", "May 18-24", "May 25-31"):
        rs = by_week.get(wk, [])
        if not rs: continue
        n2 = len(rs); w2 = sum(1 for r in rs if r["won"]); p2 = sum(r["pnl"] for r in rs)
        print(f"  {wk}  N={n2:>2}  Wins={w2:>2}  WR={w2/n2*100 if n2 else 0:>5.1f}%  P&L=${p2:>+6.0f}")

    # Trade-by-trade detail
    print("\n--- Trade-by-trade detail ---")
    print(f"  {'Date':<10} {'City':<14} {'Ticker':<24} {'Bet':<4} {'Stake':>6} {'Settle':<7} {'P&L':>8}")
    for r in sorted(results, key=lambda r: (r["date"], r["city"])):
        print(f"  {str(r['date']):<10} {r['city']:<14} {r['ticker']:<24} "
              f"{r['side_bet'].upper():<4} ${r['stake']:>4.0f}  {r['settle']:<7} ${r['pnl']:>+6.0f}")

    # Comparison to actual May 9-10 trades
    print("\n" + "=" * 88)
    print("COMPARISON to actual May 9-10 trades")
    print("=" * 88)
    print(f"  Actual (May 9-10):  8 trades, 6 wins (75% WR), +$112  →  $14/trade")
    print(f"  Hypothetical (May 11-31, blocked):  {n} trades, {wins} wins ({wins/n*100 if n else 0:.1f}% WR), ${pnl_total:+.0f}  →  ${pnl_total/n if n else 0:+.2f}/trade")


if __name__ == "__main__":
    main()
