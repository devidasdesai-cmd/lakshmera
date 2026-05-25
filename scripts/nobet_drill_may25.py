"""
Drill-down: edge_too_low signals where edge_yes was -0.05 to 0.00
(would have been NO-side bets, just barely below threshold).
Also: contract-count capped at 200 to match production trader.py.
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
from model import compute_stake_cap

ANALYSIS_SINCE = "2026-05-14"
MAX_CONTRACTS = 200  # production cap


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
    if won:
        return contracts * (1.0 - price) * 0.93
    return -contracts * price


def main():
    c = conn(); cur = c.cursor()
    cur.execute("""
      SELECT DISTINCT ON (s.ticker, s.reason)
          s.ticker, s.city, s.our_probability::float, s.market_probability::float,
          s.edge::float, s.reason, s.created_at, b.result
      FROM signals s
      JOIN blocked_results_b3 b ON b.ticker = s.ticker
      WHERE s.action='NO_BET' AND s.created_at >= %s
        AND s.reason IN ('edge_too_low','yes_price_too_high','yes_market_price_too_high',
                          'tail_no_banned','bucket_yes_banned','suspicious_edge_max_exceeded')
        AND b.result IN ('yes','no')
      ORDER BY s.ticker, s.reason, s.created_at DESC
    """, (ANALYSIS_SINCE,))
    rows = cur.fetchall()
    cur.close(); c.close()

    # ============ DRILL 1: edge_too_low NO-side bets ============
    print("=" * 90)
    print("DRILL: edge_too_low — NO-side opportunities (edge_yes negative, NO edge near threshold)")
    print("=" * 90)
    no_side = []
    for tk, city, op, mp, eg, rs, ts, res in rows:
        if rs != "edge_too_low": continue
        if op >= mp: continue   # we'd bet YES, not NO
        d = parse_dir(tk)
        side = "no"
        won = (res == "no")
        stake = compute_stake_cap("no", d, 1.0 - mp)
        no_side.append({
            "tk": tk, "city": city, "op": op, "mp": mp, "edge": eg,
            "dir": d, "won": won, "stake": stake,
            "pnl": pnl("no", mp, won, stake),
        })

    print(f"\nTotal NO-side edge_too_low (settled): {len(no_side)}")
    n = len(no_side); w = sum(1 for x in no_side if x["won"]); p = sum(x["pnl"] for x in no_side)
    if n:
        print(f"  Overall WR={w/n*100:.1f}%  P&L=${p:+.0f}  per-bet={p/n:+.2f}")

    print("\nBy market YES band (NO buys high-priced contract when mkt YES is low):")
    for lo, hi in [(0.00,0.05),(0.05,0.10),(0.10,0.15),(0.15,0.20),(0.20,0.30),
                   (0.30,0.50),(0.50,0.80),(0.80,1.00)]:
        sub = [x for x in no_side if lo <= x["mp"] < hi]
        if not sub: continue
        n=len(sub); w=sum(1 for x in sub if x["won"]); p=sum(x["pnl"] for x in sub)
        print(f"  mkt YES {lo:.2f}-{hi:.2f}  N={n:>3}  W={w:>3}  WR={w/n*100:>5.1f}%  P&L=${p:>+7.0f}  per={p/n:+.2f}")

    print("\nBy direction:")
    for d in ("above","bucket","?"):
        sub = [x for x in no_side if x["dir"] == d]
        if not sub: continue
        n=len(sub); w=sum(1 for x in sub if x["won"]); p=sum(x["pnl"] for x in sub)
        print(f"  {d:<7}  N={n:>3}  W={w:>3}  WR={w/n*100:>5.1f}%  P&L=${p:>+7.0f}")

    # ============ DRILL 2: 50-65% band split bucket vs tail ============
    print("\n" + "=" * 90)
    print("DRILL: yes_price_too_high — full 50-65% band, split bucket vs tail")
    print("=" * 90)
    items = [x for x in [
        {"tk":tk,"city":c2,"op":op,"mp":mp,"edge":eg,"dir":parse_dir(tk),
         "won":(res=="no"),
         "stake":compute_stake_cap("no",parse_dir(tk),1.0-mp),
         "pnl":pnl("no",mp,res=="no",compute_stake_cap("no",parse_dir(tk),1.0-mp))}
        for tk,c2,op,mp,eg,rs,ts,res in rows if rs=="yes_price_too_high"
    ] if 0.50 <= x["mp"] < 0.65]
    for d in ("bucket","above"):
        sub = [x for x in items if x["dir"] == d]
        if not sub: continue
        n=len(sub); w=sum(1 for x in sub if x["won"]); p=sum(x["pnl"] for x in sub)
        print(f"  {d:<7}  N={n:>3}  W={w:>3}  WR={w/n*100:>5.1f}%  P&L=${p:>+7.0f}")

    # ============ DRILL 3: 65-80% band on yes_price_too_high  ============
    print("\n" + "=" * 90)
    print("DRILL: yes_price_too_high — 60-65 and 65-100 detailed listing")
    print("=" * 90)
    raw = [{"tk":tk,"city":c2,"mp":mp,"dir":parse_dir(tk),
            "won":(res=="no"),
            "stake":compute_stake_cap("no",parse_dir(tk),1.0-mp),
            "pnl":pnl("no",mp,res=="no",compute_stake_cap("no",parse_dir(tk),1.0-mp))}
           for tk,c2,op,mp,eg,rs,ts,res in rows if rs=="yes_price_too_high"]
    for lo, hi in [(0.60,0.65),(0.65,0.80),(0.80,1.00)]:
        sub = [x for x in raw if lo <= x["mp"] < hi]
        if not sub: continue
        print(f"\n  Band {lo:.2f}-{hi:.2f}  N={len(sub)}")
        for x in sorted(sub, key=lambda x: -x["pnl"]):
            print(f"    {x['tk']:<36} {x['city']:<13} mkt={x['mp']:.2f} dir={x['dir']:<7} "
                  f"won={x['won']!s:<5} pnl={x['pnl']:+.0f}")

    # ============ DRILL 4: Bucket NO in 40-50% band (where May 22 said danger zone) ============
    print("\n" + "=" * 90)
    print("DRILL: yes_price_too_high in 40-50% band — bucket vs tail")
    print("=" * 90)
    items = [x for x in raw if 0.40 <= x["mp"] < 0.50]
    for d in ("bucket","above"):
        sub = [x for x in items if x["dir"] == d]
        if not sub: continue
        n=len(sub); w=sum(1 for x in sub if x["won"]); p=sum(x["pnl"] for x in sub)
        print(f"  {d:<7}  N={n:>3}  W={w:>3}  WR={w/n*100:>5.1f}%  P&L=${p:>+7.0f}")


if __name__ == "__main__":
    main()
