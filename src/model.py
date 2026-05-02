from datetime import date
from weather import get_ensemble_temps, probability_above, probability_below


def estimate_probability(city: dict, target_date: date, threshold_f: float, direction: str) -> float | None:
    """
    Estimate the probability that a city's high temp exceeds (or stays below)
    a threshold on a given date, using GFS ensemble forecasts.

    direction: 'above' or 'below'
    Returns probability (0.0–1.0) or None if data is unavailable.
    """
    temps = get_ensemble_temps(city["lat"], city["lon"], target_date, city["tz"])
    if not temps:
        print(f"  No ensemble data for {city['name']} on {target_date}")
        return None

    print(f"  {city['name']} {target_date}: {len(temps)} ensemble members, "
          f"mean={sum(temps)/len(temps):.1f}°F, "
          f"min={min(temps):.1f}°F, max={max(temps):.1f}°F")

    if direction == "above":
        return probability_above(temps, threshold_f)
    else:
        return probability_below(temps, threshold_f)


def calculate_edge(our_prob: float, market_prob: float) -> float:
    """
    Positive edge → YES is underpriced (bet YES).
    Negative edge → NO is underpriced (bet NO, i.e. fade YES).
    """
    return our_prob - market_prob


def kelly_size(edge: float, capital: float, kelly_cap: float) -> float:
    """
    Simplified Kelly Criterion for a binary market with ~1:1 odds.
    Returns dollar amount to bet, capped at kelly_cap * capital.
    """
    if edge <= 0:
        return 0.0
    fraction = min(edge, kelly_cap)
    return fraction * capital
