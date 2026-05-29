"""
Find winning trends in bets we DIDN'T place.
Focus: edge_too_low signals (223 settled, the biggest unexplored bucket).
Goal: find a sub-pattern with positive hypothetical P&L at reasonable WR.
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
from model import compute_stake_cap

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


def pnl(side, mkt_p, won, stake):
    price = max(0.01, min(0.99, mkt_p if side == "yes" else 1.0 - mkt_p))
    contracts = min(MAX_CONTRACTS, max(1, int(stake / price)))
    return contracts * (1.0 - price) * 0.93 if won else -contracts * price


def fetch_edge_too_low():
    c = conn(); cur = c.cursor()
    cur.execute("""
      SELECT DISTINCT ON (s.ticker)
        s.ticker, s.city, s.our_probability::float, s.market_probability::float,
        s.edge::float, s.created_at, b.result
      FROM signals s
      JOIN blocked_results_b3 b ON b.ticker = s.ticker
      WHERE s.action='NO_BET' AND s.reason='edge_too_low'
        AND s.created_at >= '2026-05-14'
        AND b.result IN ('yes','no')
      ORDER BY s.ticker, s.created_at DESC
    """)
    rows = cur.fetchall()
    cur.close(); c.close()
    return rows


def build(rows):
    out = []
    for tk, ct, op, mp, eg, ts, res in rows:
        d = parse_dir(tk)
        # Imputed side: whichever side has positive raw edge
        # If op > mp: YES looks underpriced (we'd want to BET YES)
        # If op < mp: NO looks underpriced (we'd want to BET NO)
        if op == mp:
            continue
        side = "yes" if op > mp else "no"
        # Post-fee edge on the side we'd bet
        if side == "yes":
            post_fee = op - mp - FEE * (1 - mp)
        else:
            post_fee = (1 - op) - (1 - mp) - FEE * mp
        won = (res == side)
        stake = compute_stake_cap(side, d, mp if side == "yes" else 1.0 - mp)
        out.append({
            "tk": tk, "city": ct, "op": op, "mp": mp, "edge_yes": eg,
            "dir": d, "side": side, "post_fee_edge": post_fee,
            "won": won, "stake": stake,
            "pnl": pnl(side, mp, won, stake),
        })
    return out


def show(label, items):
    if not items:
        print(f"  {label}: (no samples)")
        return
    n = len(items); w = sum(1 for x in items if x["won"]); p = sum(x["pnl"] for x in items)
    wr = w / n * 100
    print(f"  {label:<40} N={n:>3}  W={w:>3}  WR={wr:>5.1f}%  P&L=${p:>+7.0f}  per={p/n:+.2f}")


def main():
    rows = fetch_edge_too_low()
    items = build(rows)
    print(f"\nTotal settled edge_too_low signals: {len(items)}\n")

    # ============ A. Split by imputed side ============
    print("=" * 90)
    print("A. EDGE_TOO_LOW split by imputed side")
    print("=" * 90)
    yes_items = [x for x in items if x["side"] == "yes"]
    no_items = [x for x in items if x["side"] == "no"]
    show("All YES-side", yes_items)
    show("All NO-side", no_items)

    # ============ B. YES-side detail ============
    print("\n" + "=" * 90)
    print("B. YES-SIDE edge_too_low — by post-fee edge band")
    print("=" * 90)
    for lo, hi in [(0.04, 0.05), (0.02, 0.04), (0.00, 0.02),
                   (-0.02, 0.00), (-0.05, -0.02), (-1.0, -0.05)]:
        sub = [x for x in yes_items if lo <= x["post_fee_edge"] < hi]
        show(f"post-fee edge {lo:+.2f}..{hi:+.2f}", sub)

    print("\nB.1 YES-side by market YES price band:")
    for lo, hi in [(0.00, 0.05), (0.05, 0.10), (0.10, 0.20),
                   (0.20, 0.35), (0.35, 0.50), (0.50, 0.80), (0.80, 1.0)]:
        sub = [x for x in yes_items if lo <= x["mp"] < hi]
        show(f"mkt YES {lo:.2f}-{hi:.2f}", sub)

    print("\nB.2 YES-side by direction:")
    for d in ("above", "bucket"):
        show(f"direction {d}", [x for x in yes_items if x["dir"] == d])

    print("\nB.3 YES-side by city (top 6 by P&L):")
    by_city = defaultdict(list)
    for x in yes_items: by_city[x["city"]].append(x)
    ranked = sorted(by_city.items(), key=lambda kv: -sum(x["pnl"] for x in kv[1]))
    for city, sub in ranked[:6]:
        show(city, sub)
    print("  ... bottom 4:")
    for city, sub in ranked[-4:]:
        show(city, sub)

    # ============ C. Cross-cut: YES bets where market is mildly NO (the inverse) ============
    print("\n" + "=" * 90)
    print("C. INVERSE PATTERN: YES bets where market mildly leans NO (35-50% mkt YES)")
    print("    This mirrors the lean-YES bucket NO carve-out, on the YES side.")
    print("=" * 90)
    inv_all = [x for x in yes_items if 0.35 <= x["mp"] < 0.50]
    show("All directions", inv_all)
    show("  bucket only", [x for x in inv_all if x["dir"] == "bucket"])
    show("  tail (above)", [x for x in inv_all if x["dir"] == "above"])

    # Also check the slightly wider 30-50% band
    print("\n  Widening to 30-50% mkt YES band:")
    inv_wider = [x for x in yes_items if 0.30 <= x["mp"] < 0.50]
    show("All directions", inv_wider)
    show("  bucket only", [x for x in inv_wider if x["dir"] == "bucket"])
    show("  tail (above)", [x for x in inv_wider if x["dir"] == "above"])

    # ============ D. Best WR sub-pattern brute search ============
    print("\n" + "=" * 90)
    print("D. BRUTE-FORCE SCAN: where do YES bets win in the edge_too_low pool?")
    print("=" * 90)
    # All combinations of (direction, mkt price band, edge magnitude)
    print("Scanning for high-WR/profitable sub-groups (min N=8):")
    bands_price = [(0.00,0.05),(0.05,0.15),(0.15,0.30),(0.30,0.50),(0.50,0.70),(0.70,1.0)]
    bands_edge = [(0.0, 0.02),(0.02, 0.05),(-0.02, 0.0),(-0.05,-0.02),(-1, -0.05)]
    candidates = []
    for d in ("above","bucket"):
        for pl, ph in bands_price:
            for el, eh in bands_edge:
                sub = [x for x in yes_items if x["dir"]==d and pl<=x["mp"]<ph and el<=x["post_fee_edge"]<eh]
                if len(sub) < 8: continue
                n=len(sub); w=sum(1 for x in sub if x["won"]); p=sum(x["pnl"] for x in sub)
                wr = w/n*100
                candidates.append((p, wr, n, d, pl, ph, el, eh, sub))
    candidates.sort(key=lambda x: -x[0])
    print(f"{'P&L':>8}  {'WR':>5}  {'N':>3}  {'Dir':<7}  {'MktBand':<10}  {'EdgeBand':<14}")
    for p, wr, n, d, pl, ph, el, eh, _ in candidates[:10]:
        print(f"  ${p:>+6.0f}  {wr:>4.1f}%  {n:>3}  {d:<7}  {pl:.2f}-{ph:.2f}   {el:+.2f}..{eh:+.2f}")

    # ============ E. NO-side scan for completeness ============
    print("\n" + "=" * 90)
    print("E. NO-side edge_too_low — by direction × price band")
    print("=" * 90)
    for d in ("above","bucket"):
        print(f"\n  Direction {d}:")
        for pl, ph in [(0.00,0.10),(0.10,0.20),(0.20,0.30),(0.30,0.50),(0.50,1.0)]:
            sub = [x for x in no_items if x["dir"]==d and pl<=x["mp"]<ph]
            show(f"    mkt YES {pl:.2f}-{ph:.2f}", sub)


if __name__ == "__main__":
    main()
