"""
Calibration diagnostic: is our_probability informative or noise?

Approach:
  1. Pull every settled paper trade with (our_probability, actual outcome)
  2. Fit isotonic regression (Pool Adjacent Violators algorithm) — the optimal
     monotonic mapping from raw score → empirical YES rate
  3. Compare predictive performance via Brier score:
       - Constant baseline (predict 20% always)
       - Current calibration (use our_probability directly)
       - Isotonic re-mapping (refit)
  4. Plot the calibration curve so we can see whether the isotonic fit is:
       - Roughly flat → Problem B (no signal)
       - Smooth monotonic → Problem A (calibrate and ship)

No scipy/sklearn/numpy needed — pure Python.
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

WINDOW_DAYS = 60   # how far back to pull data; long enough for stable fit
N_FOLDS = 5        # for out-of-fold validation


def conn():
    return psycopg2.connect(os.environ["SUPABASE_DB_URL"])


def pull_data():
    """Return list of (our_p, side, result, ticker, created_at)."""
    c = conn(); cur = c.cursor()
    cur.execute(f"""
      SELECT our_probability::float, side, result, ticker, created_at
      FROM trades
      WHERE paper_trade=TRUE AND settled=TRUE
        AND our_probability IS NOT NULL AND result IS NOT NULL
        AND created_at >= NOW() - INTERVAL '{WINDOW_DAYS} days'
      ORDER BY created_at
    """)
    rows = cur.fetchall()
    cur.close(); c.close()
    return rows


def pav_isotonic(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """
    Pool Adjacent Violators. Returns (sorted_xs, fitted_ys) where fitted_ys is
    a non-decreasing isotonic regression of ys against xs.
    """
    if not xs:
        return [], []
    paired = sorted(zip(xs, ys), key=lambda t: t[0])
    sx = [p[0] for p in paired]
    sy = [float(p[1]) for p in paired]
    # Each "block" has (sum_y, count, start_idx, end_idx). Iterate L→R, merging
    # when a new block's mean violates the non-decreasing constraint.
    blocks = []
    for i, y in enumerate(sy):
        cur = [y, 1, i, i]
        while blocks and blocks[-1][0] / blocks[-1][1] > cur[0] / cur[1]:
            prev = blocks.pop()
            cur = [prev[0] + cur[0], prev[1] + cur[1], prev[2], cur[3]]
        blocks.append(cur)
    fitted = [0.0] * len(sy)
    for sum_y, n, lo, hi in blocks:
        m = sum_y / n
        for i in range(lo, hi+1):
            fitted[i] = m
    return sx, fitted


def isotonic_predict(query_x: float, sorted_xs: list[float], fitted_ys: list[float]) -> float:
    """Predict isotonic value at query_x by step-function lookup."""
    if not sorted_xs: return 0.5
    # Find rightmost x <= query_x; nearest-neighbor at boundaries
    lo, hi = 0, len(sorted_xs) - 1
    if query_x <= sorted_xs[0]: return fitted_ys[0]
    if query_x >= sorted_xs[-1]: return fitted_ys[-1]
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sorted_xs[mid] <= query_x: lo = mid
        else: hi = mid - 1
    return fitted_ys[lo]


def brier(predictions: list[float], outcomes: list[int]) -> float:
    """Mean squared error: lower is better. Perfect=0, always-wrong=1."""
    if not predictions: return 0.0
    return sum((p - y) ** 2 for p, y in zip(predictions, outcomes)) / len(predictions)


def reliability_table(our_ps: list[float], outcomes: list[int],
                      isotonic_xs: list[float] = None, isotonic_ys: list[float] = None) -> None:
    """Print observed YES rate per our_probability decile, with isotonic curve overlay."""
    bands = [(0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
             (0.20, 0.25), (0.25, 0.30), (0.30, 0.40), (0.40, 0.50),
             (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 1.01)]
    print(f"  {'Band':<13} {'N':>5} {'Actual YES':>11} {'Isotonic':>9} {'Δ from y=x':>12}")
    for lo, hi in bands:
        sub = [(p, y) for p, y in zip(our_ps, outcomes) if lo <= p < hi]
        if not sub: continue
        n = len(sub)
        actual = sum(y for _, y in sub) / n
        mid = (lo + hi) / 2
        delta = actual - mid
        if isotonic_xs:
            iso = isotonic_predict(mid, isotonic_xs, isotonic_ys)
            iso_str = f"{iso*100:>7.1f}%"
        else:
            iso_str = "       —"
        print(f"  {lo:.2f}-{hi:.2f}    {n:>5} {actual*100:>9.1f}%  {iso_str}    {delta*100:>+9.1f}pp")


def kfold_isotonic(rows, k=5):
    """Out-of-fold Brier for isotonic refit."""
    out_oof_preds = [0.0] * len(rows)
    out_oof_idx = list(range(len(rows)))
    fold_size = len(rows) // k
    for f in range(k):
        test_lo = f * fold_size
        test_hi = (f + 1) * fold_size if f < k - 1 else len(rows)
        test_idx = set(range(test_lo, test_hi))
        train_xs, train_ys = [], []
        for i, (p, side, res, _, _) in enumerate(rows):
            if i in test_idx: continue
            train_xs.append(p); train_ys.append(1 if res == "yes" else 0)
        sx, sy = pav_isotonic(train_xs, train_ys)
        for i in range(test_lo, test_hi):
            out_oof_preds[i] = isotonic_predict(rows[i][0], sx, sy)
    return out_oof_preds


def main():
    print("Pulling data...")
    rows = pull_data()
    print(f"  Settled paper trades with our_probability + result: {len(rows)}\n")

    our_ps = [r[0] for r in rows]
    outcomes = [1 if r[2] == "yes" else 0 for r in rows]

    yes_count = sum(outcomes)
    base_rate = yes_count / len(outcomes)
    print(f"Base rate (actual YES frequency): {base_rate*100:.1f}%\n")

    # ── Fit isotonic regression on the whole dataset (descriptive) ──
    sx, sy = pav_isotonic(our_ps, outcomes)

    # ── Reliability table ──
    print("=" * 88)
    print("RELIABILITY: actual YES rate by our_probability band")
    print("=" * 88)
    reliability_table(our_ps, outcomes, sx, sy)

    # ── Inspect the isotonic curve at fixed query points ──
    print("\n" + "=" * 88)
    print("ISOTONIC MAPPING — what our model's value 'should' be")
    print("=" * 88)
    print(f"  {'Our model says':<16} {'Isotonic suggests':<20} {'Direction':<25}")
    for q in [0.02, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
        iso = isotonic_predict(q, sx, sy)
        arrow = "≈" if abs(iso - q) < 0.02 else ("↑" if iso > q else "↓")
        print(f"  {q*100:>5.1f}%           {iso*100:>5.1f}%               {arrow}")

    # Range of isotonic outputs — is it flat or spread?
    iso_min = min(sy); iso_max = max(sy)
    print(f"\n  Isotonic output range: {iso_min*100:.1f}% .. {iso_max*100:.1f}%  "
          f"(spread = {(iso_max-iso_min)*100:.1f}pp)")

    # ── Brier scores ──
    print("\n" + "=" * 88)
    print("BRIER SCORES (lower = better; 0 = perfect, 0.25 = always guess 50%)")
    print("=" * 88)
    # 1. Always predict base rate
    const_pred = [base_rate] * len(rows)
    b_const = brier(const_pred, outcomes)
    # 2. Current calibration: use our_probability directly
    b_cur = brier(our_ps, outcomes)
    # 3. In-sample isotonic
    in_sample_iso = [isotonic_predict(p, sx, sy) for p in our_ps]
    b_iso = brier(in_sample_iso, outcomes)
    # 4. Out-of-fold isotonic (honest)
    oof = kfold_isotonic(rows, k=N_FOLDS)
    b_oof = brier(oof, outcomes)

    print(f"  Constant baseline (always predict {base_rate*100:.0f}%):  Brier = {b_const:.4f}")
    print(f"  Current model (use our_probability directly):    Brier = {b_cur:.4f}")
    print(f"  Isotonic re-mapping (in-sample):                 Brier = {b_iso:.4f}")
    print(f"  Isotonic re-mapping (out-of-fold, k={N_FOLDS}):         Brier = {b_oof:.4f}  ← honest")

    # ── Interpretation ──
    print("\n" + "=" * 88)
    print("DIAGNOSIS")
    print("=" * 88)
    delta_current_vs_const = b_const - b_cur
    delta_iso_vs_const = b_const - b_oof
    print(f"  Current vs constant baseline: {delta_current_vs_const:+.4f}")
    print(f"  Isotonic vs constant baseline: {delta_iso_vs_const:+.4f}")
    if delta_iso_vs_const > 0.005:
        print("\n  → Isotonic refit beats the 'always predict base rate' baseline by a meaningful")
        print("    margin. Our raw model has SOME signal that calibration can extract.")
        print("    PROBLEM A: ship the isotonic mapping.")
    elif delta_iso_vs_const > 0.001:
        print("\n  → Isotonic barely beats baseline. Our model has marginal signal.")
        print("    Calibration helps a little; consider if the work is worth it.")
    else:
        print("\n  → Isotonic does NOT beat the 'always predict base rate' baseline.")
        print("    PROBLEM B: our raw probabilities have no extractable signal at this resolution.")
        print("    Calibration won't save us. Need to fix the input (model itself).")

    # ── Bonus: by direction, since bucket vs tail may behave differently ──
    print("\n" + "=" * 88)
    print("BY DIRECTION (bucket vs tail) — do they have different signal quality?")
    print("=" * 88)
    for d_label, d_filter in [("Bucket", "B"), ("Tail (above)", "T")]:
        sub_rows = [r for r in rows if r[3].split("-")[-1].startswith(d_filter)]
        if not sub_rows: continue
        sub_ps = [r[0] for r in sub_rows]
        sub_out = [1 if r[2] == "yes" else 0 for r in sub_rows]
        sub_base = sum(sub_out) / len(sub_out)
        sub_const = [sub_base] * len(sub_rows)
        b_sub_const = brier(sub_const, sub_out)
        b_sub_cur = brier(sub_ps, sub_out)
        sub_sx, sub_sy = pav_isotonic(sub_ps, sub_out)
        b_sub_iso = brier([isotonic_predict(p, sub_sx, sub_sy) for p in sub_ps], sub_out)
        print(f"  {d_label:<14} N={len(sub_rows):>3}  base={sub_base*100:>4.1f}%  "
              f"const={b_sub_const:.4f}  current={b_sub_cur:.4f}  isotonic={b_sub_iso:.4f}")


if __name__ == "__main__":
    main()
