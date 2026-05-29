"""
Option B Phase 1 — empirical (city, direction, market-price-band) hit-rate validation.

Build a cell hit-rate table from May 1-13 settled trades, then simulate two
candidate decision rules against May 14-28 signals and compare to actual P&L.

  Stage A (additive): keep current rules; ADD bets where current rule vetoes
                      but cell history is favorable. Cannot remove bets.
  Stage B (replacement): bet purely on cell history; drop our_probability.

For each candidate rule, report:
  - Total simulated P&L vs actual P&L
  - Currently-winning bets that would be skipped (Stage B only)
  - New bets that would be added
  - Cell-by-cell breakdown of where the value comes from
"""
from __future__ import annotations
import os, sys, time
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
from kalshi_client import KalshiClient

# ───── Configuration ─────
TRAIN_START = "2026-05-01"
TRAIN_END   = "2026-05-14"   # exclusive
TEST_START  = "2026-05-14"
TEST_END    = "2026-05-29"   # exclusive (so includes May 28 data)

MIN_CELL_N     = 8        # cell must have ≥ this many historical samples
MIN_MARGIN     = 0.04     # WR must beat breakeven by this much

# Stake tiers (mirrors model.compute_stake_cap)
def stake_cap(side: str, direction: str, price: float) -> int:
    if side == "no":
        if 0.80 <= price < 0.95: return 300
        if direction == "bucket" and 0.60 <= price < 0.80: return 200
    return 100

# Reduced-stake cities for NO (mirrors today's shipped change)
REDUCED_STAKE_NO_CITIES = ("Oklahoma City", "DC", "Phoenix", "Los Angeles")
REDUCED_STAKE_NO_CAP = 50

MAX_CONTRACTS = 200
FEE = 0.07


def conn():
    return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def parse_dir(t: str) -> str:
    p = t.split("-")
    if len(p) < 3: return "?"
    if p[-1].startswith("T"): return "above"
    if p[-1].startswith("B"): return "bucket"
    return "?"


SERIES_TO_CITY = {
    "KXHIGHTDAL":"Dallas","KXHIGHTHOU":"Houston","KXHIGHNY":"New York","KXHIGHNY0":"New York",
    "KXHIGHTBOS":"Boston","KXHIGHTMIN":"Minneapolis","KXHIGHLAX":"Los Angeles",
    "KXHIGHTPHX":"Phoenix","KXHIGHTDC":"DC","KXHIGHTLV":"Las Vegas",
    "KXHIGHTSEA":"Seattle","KXHIGHTSATX":"San Antonio","KXHIGHTSFO":"San Francisco",
    "KXHIGHTOKC":"Oklahoma City",
}
def parse_city(t: str) -> str:
    return SERIES_TO_CITY.get(t.split("-")[0], t.split("-")[0])


def price_band(p: float) -> tuple[float, float]:
    """Bucket market YES into bands."""
    bands = [(0,0.05),(0.05,0.10),(0.10,0.20),(0.20,0.35),
             (0.35,0.50),(0.50,0.65),(0.65,0.80),(0.80,0.95),(0.95,1.0)]
    for lo, hi in bands:
        if lo <= p < hi:
            return (lo, hi)
    return (0.95, 1.0)


def hypothetical_pnl(side: str, mkt_p: float, won: bool, stake: int) -> float:
    price = max(0.01, min(0.99, mkt_p if side == "yes" else 1.0 - mkt_p))
    contracts = min(MAX_CONTRACTS, max(1, int(stake / price)))
    return contracts * (1.0 - price) * 0.93 if won else -contracts * price


def breakeven_no_wr(mkt_p: float) -> float:
    """Breakeven win rate for buying NO at price (1 - mkt_p)."""
    p_no = 1.0 - mkt_p
    return p_no / (p_no + mkt_p * 0.93)


# ============ Phase 1.1 — Build the cell table from training data ============
def build_cell_table():
    """
    From May 1-13 settled trades, compute YES rate by (city, direction, price band).
    Returns: dict (city, direction, band) → {"n": int, "yes": int, "no": int, "yes_rate": float}
    """
    c = conn(); cur = c.cursor()
    cur.execute(f"""
      SELECT ticker, side, market_probability::float, result
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND created_at >= '{TRAIN_START}' AND created_at < '{TRAIN_END}'
        AND market_probability IS NOT NULL AND result IS NOT NULL
    """)
    cells = defaultdict(lambda: {"n": 0, "yes": 0, "no": 0})
    for tk, side, mp, res in cur.fetchall():
        city = parse_city(tk); d = parse_dir(tk)
        if city.startswith("KXRAIN"): continue  # skip rain
        band = price_band(mp)
        k = (city, d, band)
        cells[k]["n"] += 1
        if res == "yes": cells[k]["yes"] += 1
        else: cells[k]["no"] += 1
    cur.close(); c.close()
    for k, v in cells.items():
        v["yes_rate"] = v["yes"] / v["n"] if v["n"] else 0.0
        v["no_rate"]  = v["no"] / v["n"] if v["n"] else 0.0
    return cells


# ============ Phase 1.2 — Pull test-window signals + outcomes ============
def fetch_test_signals_with_results():
    """
    For every signal in May 14-28, find the actual settlement outcome via:
      1. trades.result if a trade was placed
      2. blocked_results_b3.result for cached blocks
      3. Kalshi API for the rest
    Returns rows: (ticker, city, our_p, mkt_p, action, reason, result)
    """
    c = conn(); cur = c.cursor()
    cur.execute(f"""
      SELECT DISTINCT ON (s.ticker)
        s.ticker, s.our_probability::float, s.market_probability::float,
        s.action, s.reason, s.created_at,
        COALESCE(t.result, b.result) AS settlement
      FROM signals s
      LEFT JOIN trades t ON t.ticker = s.ticker AND t.paper_trade=TRUE AND t.settled=TRUE
      LEFT JOIN blocked_results_b3 b ON b.ticker = s.ticker
      WHERE s.created_at >= '{TEST_START}' AND s.created_at < '{TEST_END}'
      ORDER BY s.ticker, s.created_at ASC
    """)
    rows = cur.fetchall()
    cur.close(); c.close()
    return rows


def settle_missing(rows):
    """Fill in Kalshi results for any tickers without cached settlement."""
    client = KalshiClient()
    out = []
    misses = [r for r in rows if r[6] is None]
    print(f"  Resolving {len(misses)} unsettled tickers via Kalshi...")
    c = conn(); cur = c.cursor()
    for i, r in enumerate(misses, 1):
        tk = r[0]
        try:
            mkt = client.get_market(tk)
            res = (mkt.get("result") or "").lower() or None
        except Exception:
            res = None
        if res in ("yes", "no"):
            try:
                cur.execute(
                    "INSERT INTO blocked_results_b3(ticker, result) VALUES (%s, %s) "
                    "ON CONFLICT (ticker) DO UPDATE SET result = EXCLUDED.result",
                    (tk, res),
                ); c.commit()
            except Exception:
                c.rollback()
        if i % 50 == 0: print(f"    ...{i}/{len(misses)}")
        time.sleep(0.04)
    cur.close(); c.close()
    # Re-pull with refreshed cache
    return fetch_test_signals_with_results()


# ============ Phase 1.3 — Simulate ============
def simulate(rows, cells, mode):
    """
    mode = 'actual' | 'stage_a' | 'stage_b'
    """
    placed = []   # list of dicts with hypothetical P&L
    by_cat = defaultdict(lambda: {"n":0,"pnl":0.0,"w":0})

    for tk, op, mp, action, reason, ts, settlement in rows:
        if settlement not in ("yes", "no"):
            continue  # can't simulate without outcome
        city = parse_city(tk); d = parse_dir(tk)
        if city.startswith("KXRAIN"): continue
        if mp is None: continue
        band = price_band(mp)
        cell = cells.get((city, d, band), None)

        # Current rule outcome: the action recorded in signals
        current_placed = (action in ("BET_YES", "BET_NO"))
        current_side = "yes" if action == "BET_YES" else ("no" if action == "BET_NO" else None)

        # Cell-rule evaluation: is this cell favorable for a NO bet?
        # (We're not betting YES under any scenario per today's change.)
        cell_favorable_no = False
        if cell and cell["n"] >= MIN_CELL_N:
            no_wr = cell["no_rate"]
            be = breakeven_no_wr(mp)
            if no_wr - be >= MIN_MARGIN:
                cell_favorable_no = True
        # Skip cells where the NO buy price would be too extreme (sanity)
        # Already inherently handled by breakeven calc.

        # Decide whether to bet under each mode
        if mode == "actual":
            if not current_placed: continue
            side = current_side
        elif mode == "stage_a":
            # Keep current rule; ADD NO bets where cell is favorable AND current vetoed AND
            # the current veto reason isn't "we already think this side is bad" (i.e., suspicious_edge,
            # tail_no_banned remain valid filters). Allow additions only for blocked categories:
            #   - yes_price_too_high (current rule blocks because mkt YES > 20%)
            #   - edge_too_low (current rule blocks because edge < 5%)
            # Stage A NEVER adds YES bets (YES is structurally broken).
            if current_placed and current_side == "yes":
                continue   # Yes-bet trades aren't placed in current rule going forward anyway
            if current_placed and current_side == "no":
                side = "no"
            elif (not current_placed) and reason in ("yes_price_too_high","edge_too_low") and cell_favorable_no:
                side = "no"
            else:
                continue
        elif mode == "stage_b":
            # Drop our_probability entirely. Bet NO when cell is favorable.
            # (No YES bets — YES is structurally broken at 2% WR.)
            if cell_favorable_no:
                side = "no"
            else:
                continue
        else:
            raise ValueError(mode)

        # Determine stake using current tier rules + city cap
        price = mp if side == "yes" else (1.0 - mp)
        stk = stake_cap(side, d, price)
        if side == "no" and city in REDUCED_STAKE_NO_CITIES:
            stk = min(stk, REDUCED_STAKE_NO_CAP)

        won = (settlement == side)
        pnl = hypothetical_pnl(side, mp, won, stk)
        placed.append({
            "ticker": tk, "city": city, "dir": d, "band": band,
            "side": side, "mkt_p": mp, "won": won, "stake": stk, "pnl": pnl,
            "current_action": action, "current_reason": reason,
        })

        cat = f"{city} / {d} / {band[0]:.2f}-{band[1]:.2f}"
        by_cat[cat]["n"] += 1
        by_cat[cat]["pnl"] += pnl
        if won: by_cat[cat]["w"] += 1

    return placed, by_cat


# ============ Phase 1.4 — Reports ============
def main():
    print("Building cell table from May 1-13 settled trades...")
    cells = build_cell_table()
    eligible = [(k,v) for k,v in cells.items() if v["n"] >= MIN_CELL_N]
    print(f"  Total cells: {len(cells)}; eligible (n≥{MIN_CELL_N}): {len(eligible)}\n")

    # Show top NO-favorable cells
    print("Top 12 NO-favorable cells (training data):")
    favorable = []
    for (city, d, band), v in cells.items():
        if v["n"] < MIN_CELL_N: continue
        # Use the band midpoint as the mkt_p proxy for breakeven
        mp_mid = (band[0] + band[1]) / 2
        be = breakeven_no_wr(mp_mid)
        margin = v["no_rate"] - be
        favorable.append((margin, city, d, band, v, be))
    favorable.sort(key=lambda x: -x[0])
    print(f"  {'City':<14} {'Dir':<8} {'Band':<11} {'N':>4} {'NO WR':>7} {'BE':>7} {'Margin':>8}")
    for margin, city, d, band, v, be in favorable[:12]:
        flag = " ✓" if margin >= MIN_MARGIN else ""
        print(f"  {city:<14} {d:<8} {band[0]:.2f}-{band[1]:.2f}  {v['n']:>4} "
              f"{v['no_rate']*100:>5.1f}%  {be*100:>5.1f}%  {margin*100:>+6.1f}%{flag}")

    print("\nPulling test-window signals + outcomes...")
    rows = fetch_test_signals_with_results()
    print(f"  Test signals: {len(rows)}")
    missing = sum(1 for r in rows if r[6] is None)
    print(f"  Missing settlement: {missing}")
    if missing > 0:
        rows = settle_missing(rows)
        missing = sum(1 for r in rows if r[6] is None)
        print(f"  After Kalshi sweep: {missing} still unsettled\n")

    print("\nRunning simulations...")
    actual, actual_cats = simulate(rows, cells, "actual")
    stage_a, stage_a_cats = simulate(rows, cells, "stage_a")
    stage_b, stage_b_cats = simulate(rows, cells, "stage_b")

    def summary(label, bets):
        n = len(bets); w = sum(1 for b in bets if b["won"]); pnl = sum(b["pnl"] for b in bets)
        wr = w/n*100 if n else 0
        stk = sum(b["stake"] for b in bets)
        roi = pnl/stk*100 if stk else 0
        print(f"  {label:<10}  N={n:>4}  W={w:>4}  WR={wr:>5.1f}%  P&L=${pnl:>+7.0f}  ROI={roi:>+5.1f}%  Stake=${stk:>6.0f}")

    print("\n" + "=" * 90)
    print("RESULTS — settled signals in May 14-28")
    print("=" * 90)
    summary("Actual",  actual)
    summary("Stage A", stage_a)
    summary("Stage B", stage_b)
    delta_a = sum(b["pnl"] for b in stage_a) - sum(b["pnl"] for b in actual)
    delta_b = sum(b["pnl"] for b in stage_b) - sum(b["pnl"] for b in actual)
    print(f"\n  Stage A vs Actual: ${delta_a:+.0f}")
    print(f"  Stage B vs Actual: ${delta_b:+.0f}")

    # ============ A. Which bets does Stage A ADD? ============
    print("\n" + "=" * 90)
    print("Stage A ADDITIONS (bets current rule vetoes that the cell rule places)")
    print("=" * 90)
    added = [b for b in stage_a if b["current_action"] == "NO_BET"]
    if added:
        n = len(added); w = sum(1 for b in added if b["won"]); pnl = sum(b["pnl"] for b in added)
        print(f"  Total: N={n} W={w} WR={w/n*100:.1f}% P&L=${pnl:+.0f}")
        by_reason = defaultdict(lambda: [0,0,0.0])
        for b in added:
            r = b["current_reason"] or "?"
            by_reason[r][0] += 1
            if b["won"]: by_reason[r][1] += 1
            by_reason[r][2] += b["pnl"]
        for r, (n,w,p) in sorted(by_reason.items(), key=lambda kv: -kv[1][2]):
            print(f"    reason={r:<32}  N={n:>3}  WR={w/n*100:>5.1f}%  P&L=${p:>+7.0f}")
    else:
        print("  (no additions — Stage A places no new bets)")

    # ============ B. Stage B currently-placed bets that B SKIPS ============
    print("\n" + "=" * 90)
    print("Stage B SKIPS (currently-placed bets the cell rule would NOT make)")
    print("=" * 90)
    actual_set = {b["ticker"] for b in actual}
    stage_b_set = {b["ticker"] for b in stage_b}
    skipped_tickers = actual_set - stage_b_set
    skipped_bets = [b for b in actual if b["ticker"] in skipped_tickers]
    if skipped_bets:
        n = len(skipped_bets); w = sum(1 for b in skipped_bets if b["won"]); pnl = sum(b["pnl"] for b in skipped_bets)
        print(f"  Total: N={n} W={w} WR={w/n*100:.1f}% P&L=${pnl:+.0f}  (these are bets we'd LOSE if we ship B)")
        by_city = defaultdict(lambda: [0,0,0.0])
        for b in skipped_bets:
            ci = b["city"]
            by_city[ci][0] += 1
            if b["won"]: by_city[ci][1] += 1
            by_city[ci][2] += b["pnl"]
        for ci, (n,w,p) in sorted(by_city.items(), key=lambda kv: kv[1][2]):
            print(f"    {ci:<14}  N={n:>3}  WR={w/n*100:>5.1f}%  P&L=${p:>+7.0f}")
    else:
        print("  (no skips — Stage B keeps every current bet)")

    # ============ C. Stage B ADDITIONS ============
    print("\n" + "=" * 90)
    print("Stage B ADDITIONS (cells current rule vetoes that B places)")
    print("=" * 90)
    added_b = [b for b in stage_b if b["ticker"] not in actual_set]
    if added_b:
        n = len(added_b); w = sum(1 for b in added_b if b["won"]); pnl = sum(b["pnl"] for b in added_b)
        print(f"  Total: N={n} W={w} WR={w/n*100:.1f}% P&L=${pnl:+.0f}")

    print()


if __name__ == "__main__":
    main()
