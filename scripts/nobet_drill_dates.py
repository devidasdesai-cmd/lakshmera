"""Show the 10 bucket-NO 50-65% samples with full date detail."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import psycopg2


def parse_dir(t: str) -> str:
    p = t.split("-")
    if len(p) < 3: return "?"
    if p[-1].startswith("T"): return "above"
    if p[-1].startswith("B"): return "bucket"
    return "?"


def main():
    c = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); cur = c.cursor()
    cur.execute("""
      SELECT DISTINCT ON (s.ticker)
          s.ticker, s.city, s.market_probability::float, s.our_probability::float,
          s.created_at, b.result
      FROM signals s
      JOIN blocked_results_b3 b ON b.ticker = s.ticker
      WHERE s.action='NO_BET' AND s.reason='yes_price_too_high'
        AND s.created_at >= '2026-05-14'
        AND b.result IN ('yes','no')
        AND s.market_probability >= 0.50
        AND s.market_probability < 0.65
      ORDER BY s.ticker, s.created_at ASC
    """)
    rows = cur.fetchall()
    cur.close(); c.close()

    bucket = [(tk, ct, mp, op, ts, res) for tk, ct, mp, op, ts, res in rows
              if parse_dir(tk) == "bucket"]
    tail = [(tk, ct, mp, op, ts, res) for tk, ct, mp, op, ts, res in rows
            if parse_dir(tk) == "above"]

    print(f"\n=== BUCKET NO blocks in 50-65% band (N={len(bucket)}) ===")
    print(f"{'Ticker':<36} {'City':<13} {'mkt YES':>8} {'Signal date (UTC)':<22} {'Target':<12} {'Result':>6}")
    for tk, ct, mp, op, ts, res in sorted(bucket, key=lambda r: r[4]):
        # ticker format: KXHIGHTLV-26MAY20-B87.5
        parts = tk.split("-")
        target = parts[1] if len(parts) >= 2 else ""
        print(f"  {tk:<34} {ct:<13} {mp:>7.2f}  {str(ts):<22} {target:<12} {res:>6}")

    if bucket:
        first = min(r[4] for r in bucket)
        last = max(r[4] for r in bucket)
        span_days = (last - first).total_seconds() / 86400
        print(f"\n  First signal: {first}")
        print(f"  Last signal:  {last}")
        print(f"  Span:         {span_days:.1f} days")
        print(f"  Avg cadence:  {span_days / max(1, len(bucket)-1):.1f} days between samples")

    print(f"\n=== TAIL (above) NO blocks in 50-65% band (N={len(tail)}) ===")
    for tk, ct, mp, op, ts, res in sorted(tail, key=lambda r: r[4]):
        parts = tk.split("-")
        target = parts[1] if len(parts) >= 2 else ""
        print(f"  {tk:<34} {ct:<13} {mp:>7.2f}  {str(ts):<22} {target:<12} {res:>6}")


if __name__ == "__main__":
    main()
