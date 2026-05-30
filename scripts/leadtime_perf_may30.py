"""
Follow-up #1: P&L and forecast accuracy by lead time.

For each settled paper trade, compute lead_days = target_date - trade_date.
Aggregate WR / P&L / Brier per lead-time bucket. Tells us whether to hard-cap
the forecast horizon, or rely on lead-time-adaptive σ in V2 to naturally
down-weight long-lead bets.

Pure DB read — no API calls.
"""
from __future__ import annotations
import os, sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

WINDOW_DAYS = 60


def conn():
    return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def parse_target_date(ticker: str):
    """Tickers look like KXHIGHTDAL-26MAY03-T79 → date(2026, 5, 3)."""
    parts = ticker.split("-")
    if len(parts) < 2: return None
    try:
        return datetime.strptime(parts[1], "%y%b%d").date()
    except ValueError:
        return None


def parse_dir(t: str) -> str:
    p = t.split("-")
    if len(p) < 3: return "?"
    return "bucket" if p[-1].startswith("B") else "above" if p[-1].startswith("T") else "?"


def brier(preds, outcomes):
    return sum((p - y) ** 2 for p, y in zip(preds, outcomes)) / len(preds) if preds else 0.0


def fetch_trades():
    c = conn(); cur = c.cursor()
    cur.execute(f"""
      SELECT ticker, side, our_probability::float, market_probability::float,
             result, pnl::float, amount_usd::float,
             created_at::date AS placed_date
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND our_probability IS NOT NULL AND result IS NOT NULL
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
    """)
    rows = cur.fetchall()
    cur.close(); c.close()

    out = []
    for tk, side, op, mp, res, pnl, stk, pd in rows:
        td = parse_target_date(tk)
        if td is None: continue
        lead = (td - pd).days
        out.append({
            "ticker": tk, "side": side, "our_p": op, "mkt_p": mp,
            "result": res, "pnl": pnl or 0, "stake": stk or 0,
            "placed": pd, "target": td, "lead": lead,
            "dir": parse_dir(tk),
        })
    return out


def main():
    rows = fetch_trades()
    print(f"Settled trades in last {WINDOW_DAYS}d: {len(rows)}")
    leads = [r["lead"] for r in rows]
    print(f"Lead-time range: {min(leads)} to {max(leads)} days\n")

    # ============ A. Aggregate by lead bucket ============
    print("=" * 90)
    print("A. P&L / WR by lead time (all sides)")
    print("=" * 90)
    buckets = [(0,1), (1,2), (2,3), (3,4), (4,5), (5,6), (6,8), (8,15)]
    print(f"  {'Lead':<10} {'N':>4} {'Wins':>5} {'WR':>6} {'P&L':>10} {'per':>9} {'Stake':>9} {'ROI':>7}")
    for lo, hi in buckets:
        sub = [r for r in rows if lo <= r["lead"] < hi]
        if not sub: continue
        n = len(sub); w = sum(1 for r in sub if r["pnl"] > 0)
        pnl = sum(r["pnl"] for r in sub); stk = sum(r["stake"] for r in sub)
        wr = w / n * 100; per = pnl / n
        roi = pnl / stk * 100 if stk else 0
        print(f"  {lo}-{hi}d      {n:>4} {w:>4}  {wr:>5.1f}% ${pnl:>+7.0f} ${per:>+7.2f} ${stk:>7.0f} {roi:>+6.1f}%")

    # ============ B. By lead × side ============
    print("\n" + "=" * 90)
    print("B. By lead time × side (NO bets carry the system; how does lead affect NO?)")
    print("=" * 90)
    for side in ("no", "yes"):
        side_rows = [r for r in rows if r["side"] == side]
        if not side_rows: continue
        print(f"\n  {side.upper()} side:")
        print(f"    {'Lead':<10} {'N':>4} {'WR':>6} {'P&L':>10} {'per':>9}")
        for lo, hi in buckets:
            sub = [r for r in side_rows if lo <= r["lead"] < hi]
            if not sub: continue
            n = len(sub); w = sum(1 for r in sub if r["pnl"] > 0)
            pnl = sum(r["pnl"] for r in sub); per = pnl / n
            wr = w/n*100
            print(f"    {lo}-{hi}d      {n:>4}  {wr:>5.1f}% ${pnl:>+7.0f} ${per:>+7.2f}")

    # ============ C. By lead × direction ============
    print("\n" + "=" * 90)
    print("C. By lead time × direction (does bucket vs tail behave differently?)")
    print("=" * 90)
    for d in ("bucket", "above"):
        d_rows = [r for r in rows if r["dir"] == d]
        if not d_rows: continue
        print(f"\n  Direction = {d}:")
        print(f"    {'Lead':<10} {'N':>4} {'WR':>6} {'P&L':>10}")
        for lo, hi in buckets:
            sub = [r for r in d_rows if lo <= r["lead"] < hi]
            if not sub: continue
            n = len(sub); w = sum(1 for r in sub if r["pnl"] > 0)
            pnl = sum(r["pnl"] for r in sub)
            print(f"    {lo}-{hi}d      {n:>4}  {w/n*100:>5.1f}% ${pnl:>+7.0f}")

    # ============ D. Our model's accuracy by lead time ============
    print("\n" + "=" * 90)
    print("D. Forecast accuracy by lead time — does our model degrade with lead?")
    print("    Brier of our_probability vs actual outcome, by lead bucket.")
    print("=" * 90)
    base = sum(1 for r in rows if r["result"] == "yes") / len(rows)
    print(f"  Overall actual YES rate: {base*100:.1f}%\n")
    print(f"  {'Lead':<10} {'N':>4} {'Actual YES':>11} {'Brier-current':>15} {'Brier-const':>13}")
    for lo, hi in buckets:
        sub = [r for r in rows if lo <= r["lead"] < hi]
        if not sub: continue
        n = len(sub)
        outs = [1 if r["result"] == "yes" else 0 for r in sub]
        preds_cur = [r["our_p"] for r in sub]
        sub_base = sum(outs) / n
        preds_const = [sub_base] * n
        b_cur = brier(preds_cur, outs); b_const = brier(preds_const, outs)
        print(f"  {lo}-{hi}d      {n:>4}  {sub_base*100:>9.1f}%   {b_cur:>7.4f}        {b_const:>7.4f}")

    # ============ E. Where do most trades live? ============
    print("\n" + "=" * 90)
    print("E. Volume distribution — what fraction of trades happen at each lead?")
    print("=" * 90)
    total = len(rows)
    for lo, hi in buckets:
        sub = [r for r in rows if lo <= r["lead"] < hi]
        if not sub: continue
        pct = len(sub) / total * 100
        bar = "█" * int(pct / 2)
        print(f"  {lo}-{hi}d: {len(sub):>4} trades  ({pct:>5.1f}%)  {bar}")


if __name__ == "__main__":
    main()
