"""
Deep analysis of NO_BET signals since May 14 2026.
Identifies sub-patterns where blocked signals would have won.

Usage: python3 scripts/nobet_analysis_may25.py
"""
from __future__ import annotations
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2
from kalshi_client import KalshiClient
from model import compute_stake_cap

ANALYSIS_SINCE = "2026-05-14"
ACTIONABLE_REASONS = (
    "yes_price_too_high",          # NO blocked: mkt YES > 20%
    "yes_market_price_too_high",   # YES blocked: mkt YES > 5%
    "tail_no_banned",
    "bucket_yes_banned",
    "suspicious_edge_max_exceeded",
    "edge_too_low",
)


def conn():
    return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def fetch_signals():
    """
    Distinct latest signal per (ticker, reason) since May 14.
    Returns rows: ticker, city, our_prob, market_prob, edge, reason, action, created_at
    """
    c = conn(); cur = c.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (ticker, reason)
            ticker, city, our_probability::float, market_probability::float,
            edge::float, reason, action, created_at
        FROM signals
        WHERE action IN ('NO_BET','SUSPICIOUS_EDGE')
          AND created_at >= %s
          AND reason = ANY(%s)
        ORDER BY ticker, reason, created_at DESC
        """,
        (ANALYSIS_SINCE, list(ACTIONABLE_REASONS)),
    )
    rows = cur.fetchall()
    cur.close(); c.close()
    return rows


def load_settlement_cache():
    """Load cached settlements from blocked_results_b3 table."""
    c = conn(); cur = c.cursor()
    cur.execute("SELECT ticker, result FROM blocked_results_b3")
    cache = {t: r for t, r in cur.fetchall()}
    cur.close(); c.close()
    return cache


def save_settlement(ticker, result):
    c = conn(); cur = c.cursor()
    cur.execute(
        "INSERT INTO blocked_results_b3(ticker, result) VALUES (%s, %s) "
        "ON CONFLICT (ticker) DO UPDATE SET result = EXCLUDED.result",
        (ticker, result),
    )
    c.commit()
    cur.close(); c.close()


def ensure_b3_pk():
    c = conn(); cur = c.cursor()
    try:
        cur.execute("ALTER TABLE blocked_results_b3 ADD PRIMARY KEY (ticker)")
        c.commit()
    except Exception:
        c.rollback()
    cur.close(); c.close()


def fetch_kalshi_results(tickers, cache):
    """Fetch settlement results from Kalshi for tickers not in cache."""
    client = KalshiClient()
    missing = [t for t in tickers if t not in cache]
    print(f"Querying Kalshi for {len(missing)} tickers (cache has {len(cache)})...")
    for i, t in enumerate(missing, 1):
        try:
            mkt = client.get_market(t)
            result = (mkt.get("result") or "").lower() or "unsettled"
            cache[t] = result
            save_settlement(t, result)
        except Exception as e:
            cache[t] = "error"
        if i % 20 == 0:
            print(f"  ...{i}/{len(missing)}")
        time.sleep(0.05)
    return cache


def parse_direction_from_ticker(ticker: str) -> str:
    """
    Very lightweight ticker parsing — we don't need exact bounds for P&L math,
    only direction.
      KXHIGHT*-...-T{n}    → tail (above)
      KXHIGHT*-...-B{n}    → bucket
      Bucket tickers usually have a 'B' prefix in the strike segment.
    """
    parts = ticker.split("-")
    if len(parts) < 3:
        return "unknown"
    strike = parts[-1]
    if strike.startswith("T"):
        return "above"
    if strike.startswith("B"):
        return "bucket"
    return "unknown"


def hypo_pnl_for_no_bet(market_prob: float, won: bool, stake_cap: int) -> float:
    """
    NO bet: buy NO at price = (1 - market_prob)
    contracts = floor(stake_cap / price)
    Win  → +contracts * (1 - price) * (1 - fee_on_profit), fee 7% of profit
    Loss → -contracts * price
    """
    price = max(0.01, min(0.99, 1.0 - market_prob))
    contracts = max(1, int(stake_cap / price))
    if won:  # NO wins means market resolved NO (the underlying YES was False)
        profit_gross = contracts * (1.0 - price)
        profit_net = profit_gross * (1.0 - 0.07)
        return profit_net
    else:
        return -contracts * price


def hypo_pnl_for_yes_bet(market_prob: float, won: bool, stake_cap: int) -> float:
    price = max(0.01, min(0.99, market_prob))
    contracts = max(1, int(stake_cap / price))
    if won:
        profit_gross = contracts * (1.0 - price)
        profit_net = profit_gross * (1.0 - 0.07)
        return profit_net
    else:
        return -contracts * price


def reason_to_side(reason: str, our_prob: float, market_prob: float) -> str:
    """
    Map reason → which side the bot would have bet on if the filter were lifted.
    """
    if reason in ("yes_market_price_too_high", "bucket_yes_banned"):
        return "yes"
    if reason in ("yes_price_too_high", "tail_no_banned"):
        return "no"
    if reason == "suspicious_edge_max_exceeded":
        # Edge >55%. If our_prob >> market_prob → would BET YES. Else BET NO.
        return "yes" if our_prob > market_prob else "no"
    if reason == "edge_too_low":
        # Whichever side has slightly positive edge
        return "yes" if our_prob > market_prob else "no"
    return "?"


def analyze():
    ensure_b3_pk()
    print(f"Pulling NO_BET signals since {ANALYSIS_SINCE}...")
    rows = fetch_signals()
    print(f"Found {len(rows)} distinct (ticker, reason) blocks.\n")

    tickers = sorted(set(r[0] for r in rows))
    cache = load_settlement_cache()
    cache = fetch_kalshi_results(tickers, cache)

    # Bucket per reason
    by_reason: dict[str, list] = defaultdict(list)
    for ticker, city, our_p, mkt_p, edge, reason, action, created_at in rows:
        result = cache.get(ticker, "error")
        if result not in ("yes", "no"):
            continue  # unsettled / error — exclude

        side = reason_to_side(reason, our_p, mkt_p)
        won = (result == side)
        direction = parse_direction_from_ticker(ticker)
        if side == "yes":
            stake = compute_stake_cap("yes", direction, mkt_p)
            pnl = hypo_pnl_for_yes_bet(mkt_p, won, stake)
        else:
            stake = compute_stake_cap("no", direction, 1.0 - mkt_p)
            pnl = hypo_pnl_for_no_bet(mkt_p, won, stake)

        by_reason[reason].append({
            "ticker": ticker, "city": city, "our_p": our_p, "mkt_p": mkt_p,
            "edge": edge, "side": side, "direction": direction,
            "result": result, "won": won, "stake": stake, "pnl": pnl,
            "created_at": created_at,
        })

    print("\n" + "=" * 88)
    print("AGGREGATE BY REASON")
    print("=" * 88)
    print(f"{'Reason':<32} {'N':>5} {'Wins':>5} {'WR':>6} {'Hypo P&L':>12} {'Per-bet':>10}")
    print("-" * 88)
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        n = len(items)
        w = sum(1 for x in items if x["won"])
        pnl = sum(x["pnl"] for x in items)
        wr = w / n * 100 if n else 0
        per = pnl / n if n else 0
        print(f"{reason:<32} {n:>5} {w:>5} {wr:>5.1f}% {pnl:>+12.0f} {per:>+10.2f}")

    # === Slice each reason by market band ===
    print("\n" + "=" * 88)
    print("SUB-PATTERN: yes_price_too_high  (NO blocked) — by market YES band")
    print("=" * 88)
    bands = [(0.20, 0.30), (0.30, 0.40), (0.40, 0.50),
             (0.50, 0.60), (0.60, 0.65), (0.65, 0.80), (0.80, 1.00)]
    items = by_reason.get("yes_price_too_high", [])
    print(f"{'Band':<14} {'N':>5} {'Wins':>5} {'WR':>7} {'Hypo P&L':>12} {'Per-bet':>10}")
    for lo, hi in bands:
        sub = [x for x in items if lo <= x["mkt_p"] < hi]
        if not sub: continue
        n = len(sub); w = sum(1 for x in sub if x["won"])
        pnl = sum(x["pnl"] for x in sub); wr = w / n * 100
        print(f"{lo:.2f}-{hi:.2f}    {n:>5} {w:>5} {wr:>6.1f}% {pnl:>+12.0f} {pnl/n:>+10.2f}")

    print("\n" + "=" * 88)
    print("SUB-PATTERN: yes_market_price_too_high  (YES blocked) — by market YES band")
    print("=" * 88)
    bands_yes = [(0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30),
                 (0.30, 0.50), (0.50, 0.80), (0.80, 1.00)]
    items = by_reason.get("yes_market_price_too_high", [])
    print(f"{'Band':<14} {'N':>5} {'Wins':>5} {'WR':>7} {'Hypo P&L':>12} {'Per-bet':>10}")
    for lo, hi in bands_yes:
        sub = [x for x in items if lo <= x["mkt_p"] < hi]
        if not sub: continue
        n = len(sub); w = sum(1 for x in sub if x["won"])
        pnl = sum(x["pnl"] for x in sub); wr = w / n * 100
        print(f"{lo:.2f}-{hi:.2f}    {n:>5} {w:>5} {wr:>6.1f}% {pnl:>+12.0f} {pnl/n:>+10.2f}")

    # === 50-65% band drill-down on yes_price_too_high (the May 22 actionable) ===
    print("\n" + "=" * 88)
    print("DRILL: yes_price_too_high in 50-65% band — by city + direction")
    print("=" * 88)
    items = [x for x in by_reason.get("yes_price_too_high", []) if 0.50 <= x["mkt_p"] < 0.65]
    by_cd = defaultdict(list)
    for x in items:
        by_cd[(x["city"], x["direction"])].append(x)
    print(f"{'City':<15} {'Dir':<8} {'N':>4} {'Wins':>5} {'WR':>7} {'Hypo P&L':>12}")
    for (city, d), sub in sorted(by_cd.items(), key=lambda kv: -sum(x["pnl"] for x in kv[1])):
        n = len(sub); w = sum(1 for x in sub if x["won"])
        pnl = sum(x["pnl"] for x in sub); wr = w / n * 100
        print(f"{city:<15} {d:<8} {n:>4} {w:>5} {wr:>6.1f}% {pnl:>+12.0f}")
    n_tot = len(items); w_tot = sum(1 for x in items if x["won"]); p_tot = sum(x["pnl"] for x in items)
    print(f"TOTAL 50-65% band: N={n_tot} WR={w_tot/n_tot*100 if n_tot else 0:.1f}% P&L=${p_tot:+.0f}")

    # === edge_too_low: is there a band of "small edge" that wins? ===
    print("\n" + "=" * 88)
    print("SUB-PATTERN: edge_too_low — by computed best-edge band")
    print("=" * 88)
    items = by_reason.get("edge_too_low", [])
    # 'edge' column stores edge_yes; reconstruct best edge approximately:
    # If our_p > mkt_p: yes side. Else no side. Use absolute disagreement as edge proxy.
    for lo, hi in [(0.00, 0.02), (0.02, 0.04), (0.04, 0.05),
                   (-0.02, 0.00), (-0.05, -0.02)]:
        sub = [x for x in items if lo <= x["edge"] < hi]
        if not sub: continue
        n = len(sub); w = sum(1 for x in sub if x["won"])
        pnl = sum(x["pnl"] for x in sub); wr = w / n * 100
        print(f"edge_yes {lo:+.2f}..{hi:+.2f}  N={n:>4} WR={wr:>5.1f}% P&L={pnl:>+10.0f} per={pnl/n:+.2f}")

    # === by city across all blocked categories ===
    print("\n" + "=" * 88)
    print("CITY ROLLUP — every actionable block (excluding edge_too_low)")
    print("=" * 88)
    all_actionable = []
    for r, items in by_reason.items():
        if r == "edge_too_low":
            continue
        all_actionable.extend(items)
    by_city = defaultdict(list)
    for x in all_actionable:
        by_city[x["city"]].append(x)
    print(f"{'City':<15} {'N':>5} {'Wins':>5} {'WR':>7} {'Hypo P&L':>12}")
    for city, sub in sorted(by_city.items(), key=lambda kv: -sum(x["pnl"] for x in kv[1])):
        n = len(sub); w = sum(1 for x in sub if x["won"])
        pnl = sum(x["pnl"] for x in sub); wr = w / n * 100
        print(f"{city:<15} {n:>5} {w:>5} {wr:>6.1f}% {pnl:>+12.0f}")

    # === SUSPICIOUS_EDGE detail ===
    print("\n" + "=" * 88)
    print("SUSPICIOUS_EDGE detail")
    print("=" * 88)
    sus = by_reason.get("suspicious_edge_max_exceeded", [])
    for x in sus:
        print(f"  {x['ticker']:<36} {x['city']:<12} our={x['our_p']:.2f} mkt={x['mkt_p']:.2f} "
              f"side={x['side']} dir={x['direction']} result={x['result']} pnl={x['pnl']:+.0f}")

    return by_reason


if __name__ == "__main__":
    analyze()
