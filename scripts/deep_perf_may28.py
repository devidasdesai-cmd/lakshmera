"""
Deep performance analysis for the last 14 days.
Goal: identify why we have green/red days and what model change could push
forward P&L consistently above $0 toward $2K/month.
"""
from __future__ import annotations
import os, sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

WINDOW_DAYS = 14


def conn():
    return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def parse_dir(t: str) -> str:
    p = t.split("-")
    if len(p) < 3: return "?"
    if p[-1].startswith("T"): return "above"
    if p[-1].startswith("B"): return "bucket"
    return "?"


def parse_city(t: str) -> str:
    series = t.split("-")[0]
    M = {
        "KXHIGHTDAL":"Dallas","KXHIGHTHOU":"Houston","KXHIGHNY":"New York",
        "KXHIGHNY0":"New York","KXHIGHTBOS":"Boston","KXHIGHTMIN":"Minneapolis",
        "KXHIGHLAX":"Los Angeles","KXHIGHTPHX":"Phoenix","KXHIGHTDC":"DC",
        "KXHIGHTLV":"Las Vegas","KXHIGHTSEA":"Seattle","KXHIGHTSATX":"San Antonio",
        "KXHIGHTSFO":"San Francisco","KXHIGHTOKC":"Oklahoma City",
    }
    return M.get(series, series)


def main():
    c = conn(); cur = c.cursor()

    # ============ A. Daily P&L (last 14 days, by target date or by settlement date?) ============
    print("=" * 95)
    print("A. DAILY P&L (last 14 days, grouped by ticker target date)")
    print("=" * 95)
    cur.execute(f"""
      SELECT SUBSTRING(ticker FROM '\\d\\d[A-Z]{{3}}\\d\\d'), side,
             COUNT(*), SUM(pnl)::float, SUM(amount_usd)::float,
             COUNT(CASE WHEN pnl > 0 THEN 1 END) AS wins
      FROM trades
      WHERE paper_trade = TRUE AND settled = TRUE
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
      GROUP BY 1, 2
      ORDER BY 1, 2
    """)
    daily = defaultdict(lambda: {"yes": [0,0,0,0], "no": [0,0,0,0]})  # [n,pnl,stake,wins]
    for dstr, side, n, pnl, stk, wins in cur.fetchall():
        if dstr is None: continue
        daily[dstr][side] = [n, pnl or 0, stk or 0, wins]

    print(f"{'Target':<10}  {'YES n/W':>9}  {'YES P&L':>10}  {'NO n/W':>9}  {'NO P&L':>10}  {'Day P&L':>10}")
    grand = 0
    for d in sorted(daily.keys()):
        ys = daily[d]["yes"]; ns = daily[d]["no"]
        day_pnl = (ys[1] or 0) + (ns[1] or 0)
        grand += day_pnl
        print(f"{d:<10}  {ys[0]:>3}/{ys[3]:>3}    ${ys[1]:>+8.0f}  "
              f"{ns[0]:>3}/{ns[3]:>3}    ${ns[1]:>+8.0f}  ${day_pnl:>+8.0f}")
    print(f"\n14-day TOTAL: ${grand:+.0f}")

    # ============ B. Aggregate by side over window ============
    print("\n" + "=" * 95)
    print(f"B. AGGREGATE by side ({WINDOW_DAYS}d window)")
    print("=" * 95)
    cur.execute(f"""
      SELECT side, COUNT(*), SUM(pnl)::float,
             COUNT(CASE WHEN pnl > 0 THEN 1 END),
             SUM(amount_usd)::float
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
      GROUP BY side
    """)
    for side, n, p, w, stk in cur.fetchall():
        wr = w/n*100 if n else 0
        per = p/n if n else 0
        roi = p/stk*100 if stk else 0
        print(f"  {side.upper():<4} n={n:>3} W={w:>3} WR={wr:>5.1f}%  P&L=${p:>+7.0f}  per=${per:+.2f}  ROI={roi:+.1f}%")

    # ============ C. By direction × side ============
    print("\n" + "=" * 95)
    print("C. SIDE × DIRECTION (which combinations are bleeding)")
    print("=" * 95)
    cur.execute(f"""
      SELECT ticker, side, pnl::float, amount_usd::float
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
    """)
    by_sd = defaultdict(lambda: {"n":0,"pnl":0,"w":0,"stk":0})
    rows = cur.fetchall()
    for tk, side, pnl, stk in rows:
        d = parse_dir(tk)
        k = (side, d)
        by_sd[k]["n"] += 1
        by_sd[k]["pnl"] += pnl or 0
        by_sd[k]["stk"] += stk or 0
        if (pnl or 0) > 0: by_sd[k]["w"] += 1
    print(f"  {'Side':<5} {'Dir':<8} {'N':>4} {'W':>4} {'WR':>6} {'P&L':>10} {'per':>9} {'ROI':>7}")
    for (s, d), v in sorted(by_sd.items(), key=lambda kv: kv[1]["pnl"]):
        wr = v["w"]/v["n"]*100 if v["n"] else 0
        per = v["pnl"]/v["n"] if v["n"] else 0
        roi = v["pnl"]/v["stk"]*100 if v["stk"] else 0
        print(f"  {s:<5} {d:<8} {v['n']:>4} {v['w']:>4} {wr:>5.1f}% ${v['pnl']:>+7.0f} ${per:>+7.2f} {roi:>+6.1f}%")

    # ============ D. By price band ============
    print("\n" + "=" * 95)
    print("D. SIDE × PRICE BAND")
    print("=" * 95)
    bands = [(0,0.05),(0.05,0.10),(0.10,0.20),(0.20,0.30),(0.30,0.50),
             (0.50,0.70),(0.70,0.85),(0.85,0.95),(0.95,1.0)]
    cur.execute(f"""
      SELECT side, price_paid::float, pnl::float, amount_usd::float
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
    """)
    rows = cur.fetchall()
    for side in ("yes", "no"):
        print(f"\n  {side.upper()} side:")
        print(f"    {'Price':<11} {'N':>4} {'W':>4} {'WR':>6} {'P&L':>10} {'ROI':>7}")
        for lo, hi in bands:
            sub = [(p, pnl or 0, s or 0) for s2, p, pnl, s in rows if s2 == side and lo <= p < hi]
            if not sub: continue
            n=len(sub); w=sum(1 for _,pnl,_ in sub if pnl>0); pnl=sum(p for _,p,_ in sub); stk=sum(s for *_,s in sub)
            wr=w/n*100; roi = pnl/stk*100 if stk else 0
            print(f"    {lo:.2f}-{hi:.2f}    {n:>4} {w:>4} {wr:>5.1f}% ${pnl:>+7.0f} {roi:>+6.1f}%")

    # ============ E. By city ============
    print("\n" + "=" * 95)
    print("E. BY CITY (sorted by P&L)")
    print("=" * 95)
    cur.execute(f"""
      SELECT ticker, pnl::float, amount_usd::float, side
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
    """)
    rows = cur.fetchall()
    by_city = defaultdict(lambda: {"n":0,"pnl":0,"w":0,"stk":0,"yes_n":0,"no_n":0,"yes_pnl":0,"no_pnl":0})
    for tk, pnl, stk, side in rows:
        ci = parse_city(tk)
        v = by_city[ci]
        v["n"] += 1; v["pnl"] += pnl or 0; v["stk"] += stk or 0
        if (pnl or 0) > 0: v["w"] += 1
        if side == "yes":
            v["yes_n"] += 1; v["yes_pnl"] += pnl or 0
        else:
            v["no_n"] += 1; v["no_pnl"] += pnl or 0
    print(f"  {'City':<14} {'N':>4} {'WR':>6} {'P&L':>10} {'YES':>12} {'NO':>12}")
    for ci, v in sorted(by_city.items(), key=lambda kv: kv[1]["pnl"]):
        wr = v["w"]/v["n"]*100 if v["n"] else 0
        print(f"  {ci:<14} {v['n']:>4} {wr:>5.1f}% ${v['pnl']:>+7.0f}  "
              f"{v['yes_n']:>2}: ${v['yes_pnl']:>+5.0f}  {v['no_n']:>2}: ${v['no_pnl']:>+5.0f}")

    # ============ F. Live carve-out audit ============
    print("\n" + "=" * 95)
    print("F. LEAN-YES BUCKET NO CARVE-OUT (since shipped May 25)")
    print("=" * 95)
    # First get placed-trade tickers tagged with the carve-out reason
    cur.execute("""
      SELECT DISTINCT t.ticker, t.side, t.price_paid::float, t.amount_usd::float,
             t.pnl::float, t.settled, t.result, t.our_probability::float,
             t.market_probability::float, t.created_at
      FROM trades t
      WHERE t.paper_trade=TRUE
        AND t.created_at >= '2026-05-25 17:00:00'
        AND EXISTS (
          SELECT 1 FROM signals s
          WHERE s.ticker = t.ticker
            AND s.reason = 'lean_yes_bucket_no_carveout'
        )
      ORDER BY t.created_at
    """)
    carveout = cur.fetchall()
    print(f"  Placed: {len(carveout)}")
    settled_co = [r for r in carveout if r[5]]
    if settled_co:
        wins = sum(1 for r in settled_co if (r[4] or 0) > 0)
        tot_pnl = sum((r[4] or 0) for r in settled_co)
        print(f"  Settled: {len(settled_co)}  Wins: {wins}  WR: {wins/len(settled_co)*100:.1f}%  P&L: ${tot_pnl:+.0f}")
        for r in settled_co:
            tk, sd, pp, st, pnl, settled, res, op, mp, ts = r
            print(f"    {tk:<32} {parse_city(tk):<13} {sd} ${st:>5.0f} @ {pp:.2f}  our={op:.2f} mkt={mp:.2f} → ${pnl:+.0f}")
    else:
        print("  No settled carve-out trades yet.")
    unsettled = [r for r in carveout if not r[5]]
    if unsettled:
        print(f"\n  Unsettled (still open): {len(unsettled)}")
        for r in unsettled[-10:]:
            tk, sd, pp, st, _, _, _, op, mp, ts = r
            print(f"    {tk:<32} {parse_city(tk):<13} {sd} ${st:>5.0f} @ {pp:.2f}  our={op:.2f} mkt={mp:.2f}")

    # ============ G. Calibration audit (last 30 days settled) ============
    print("\n" + "=" * 95)
    print("G. CALIBRATION AUDIT — actual vs. predicted by our_probability decile")
    print("=" * 95)
    cur.execute("""
      SELECT our_probability::float, side, result
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND our_probability IS NOT NULL
        AND created_at >= NOW() - INTERVAL '30 days'
    """)
    rows = cur.fetchall()
    bands = [(0,0.10),(0.10,0.20),(0.20,0.30),(0.30,0.40),(0.40,0.50),
             (0.50,0.60),(0.60,0.70),(0.70,0.80),(0.80,1.0)]
    print(f"  Our_P band       N    YES-actually   Predicted-mid")
    for lo, hi in bands:
        sub = [(p, r) for p, _, r in rows if lo <= p < hi and r is not None]
        if not sub: continue
        n = len(sub)
        yes_actual = sum(1 for _, r in sub if r == "yes")
        rate = yes_actual / n * 100
        mid = (lo+hi)/2 * 100
        flag = " ⚠" if abs(rate - mid) > 15 else ""
        print(f"  {lo:.2f}-{hi:.2f}      {n:>3}    {rate:>5.1f}%        {mid:>5.1f}%{flag}")

    # ============ H. Stake tier audit ============
    print("\n" + "=" * 95)
    print("H. STAKE TIER P&L (are bigger stakes actually winning?)")
    print("=" * 95)
    cur.execute(f"""
      SELECT amount_usd::float, side, ticker, pnl::float, price_paid::float
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
    """)
    rows = cur.fetchall()
    tiers = [(0,75),(75,125),(125,175),(175,225),(225,400)]
    print(f"  {'Stake tier':<12} {'N':>4} {'WR':>6} {'P&L':>10} {'ROI':>7}")
    for lo, hi in tiers:
        sub = [(s, p) for s, _, _, p, _ in rows if lo <= s < hi]
        if not sub: continue
        n=len(sub); w=sum(1 for _,p in sub if p>0); pnl=sum(p for _,p in sub); stk=sum(s for s,_ in sub)
        wr=w/n*100; roi=pnl/stk*100 if stk else 0
        print(f"  ${lo}-${hi}     {n:>4} {w:>3}/{wr:>4.1f}% ${pnl:>+7.0f} {roi:>+6.1f}%")

    cur.close(); c.close()


if __name__ == "__main__":
    main()
