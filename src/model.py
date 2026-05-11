from __future__ import annotations
from datetime import date
from weather import get_ensemble_temps, probability_above, probability_below, probability_between


def estimate_probability(
    city: dict,
    target_date: date,
    threshold_f: float,
    direction: str,
    low_f: float = None,
    high_f: float = None,
) -> float | None:
    """
    Estimate the probability for a Kalshi weather contract using GFS ensembles.

    direction: 'above', 'below', or 'bucket'
    low_f / high_f: required when direction == 'bucket'
    Returns probability (0.0–1.0) or None if data is unavailable.
    """
    temps = get_ensemble_temps(city["lat"], city["lon"], target_date, city["tz"])
    if not temps:
        print(f"  No ensemble data for {city['name']} on {target_date}")
        return None

    mean = sum(temps) / len(temps)
    print(f"  {city['name']} {target_date}: {len(temps)} members | "
          f"mean={mean:.1f}°F min={min(temps):.1f}°F max={max(temps):.1f}°F")

    if direction == "above":
        return probability_above(temps, threshold_f)
    elif direction == "below":
        return probability_below(temps, threshold_f)
    elif direction == "bucket" and low_f is not None and high_f is not None:
        return probability_between(temps, low_f, high_f)

    return None


def kelly_size(edge: float, capital: float, kelly_cap: float) -> float:
    """
    Simplified Kelly Criterion. Returns dollar bet, capped at kelly_cap * capital.
    """
    if edge <= 0:
        return 0.0
    return min(edge, kelly_cap) * capital


def calibrate_probability(raw_prob: float, base_rate: float = None) -> float:
    """
    Shrink raw GFS-derived probability toward a base rate.

    When the model is overconfident at extremes (e.g., raw says 0-5% YES but the
    actual outcome rate is ~22%), shrinkage toward the base rate corrects for it.

    If `base_rate` is provided (from climatology), it's used instead of the static
    TEMPERATURE_BASE_RATE — this gives city- and date-specific calibration anchors
    rather than a single global rate.

    Set CALIBRATION_ALPHA = 1.0 in config to disable shrinkage entirely.
    """
    from config import CALIBRATION_ALPHA, TEMPERATURE_BASE_RATE
    anchor = base_rate if base_rate is not None else TEMPERATURE_BASE_RATE
    return CALIBRATION_ALPHA * raw_prob + (1 - CALIBRATION_ALPHA) * anchor
