from __future__ import annotations
import math
import time
import requests
from datetime import date, timedelta


ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def get_ensemble_temps(lat: float, lon: float, target_date: date, tz: str) -> list[float]:
    """
    Fetch GFS ensemble daily max temperatures for a location on a specific date.
    Returns a list of temperatures (one per ensemble member) in Fahrenheit.
    Returns an empty list on failure so callers can skip gracefully.
    Retries up to 2 times with backoff before giving up.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": "gfs_seamless",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "temperature_unit": "fahrenheit",
        "timezone": tz,
    }

    for attempt in range(3):
        try:
            resp = requests.get(ENSEMBLE_URL, params=params, timeout=60)
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            temps = []
            for key, values in daily.items():
                if key.startswith("temperature_2m_max") and values and values[0] is not None:
                    temps.append(values[0])
            return temps
        except requests.exceptions.Timeout:
            if attempt < 2:
                wait = 10 * (attempt + 1)
                print(f"  Open-Meteo timeout (attempt {attempt+1}/3), retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Open-Meteo timeout after 3 attempts — skipping.")
                return []
        except Exception as e:
            print(f"  Open-Meteo error: {e} — skipping.")
            return []


def probability_above(temps: list[float], threshold_f: float) -> float | None:
    if not temps:
        return None
    return sum(1 for t in temps if t > threshold_f) / len(temps)


def probability_below(temps: list[float], threshold_f: float) -> float | None:
    if not temps:
        return None
    return sum(1 for t in temps if t < threshold_f) / len(temps)


def probability_between(temps: list[float], low_f: float, high_f: float) -> float | None:
    """Fraction of ensemble members where max temp falls in [low_f, high_f)."""
    if not temps:
        return None
    return sum(1 for t in temps if low_f <= t < high_f) / len(temps)


def get_historical_forecast_temps(lat: float, lon: float, target_date: date, tz: str) -> list[float]:
    """
    Fetch historical GFS forecast max temperature for a past date.
    Uses the historical-forecast API (what was forecast at the time, not live ensemble).
    Returns a list — may be single value; callers should fall back to normal CDF if len == 1.
    Returns [] on failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": "gfs_seamless",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "temperature_unit": "fahrenheit",
        "timezone": tz,
    }
    for attempt in range(3):
        try:
            resp = requests.get(HISTORICAL_FORECAST_URL, params=params, timeout=60)
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            temps = []
            for key, values in daily.items():
                if key.startswith("temperature_2m_max") and values and values[0] is not None:
                    temps.append(values[0])
            return temps
        except requests.exceptions.Timeout:
            if attempt < 2:
                wait = 10 * (attempt + 1)
                print(f"  Historical forecast timeout (attempt {attempt+1}/3), retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Historical forecast timeout after 3 attempts — skipping.")
                return []
        except Exception as e:
            print(f"  Historical forecast error: {e} — skipping.")
            return []


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def norm_probability_above(temp_f: float, threshold_f: float, sigma: float = 3.0) -> float:
    """P(actual > threshold) given a point forecast, assuming normal error with σ=3°F."""
    return 1.0 - _norm_cdf((threshold_f - temp_f) / sigma)


def norm_probability_below(temp_f: float, threshold_f: float, sigma: float = 3.0) -> float:
    """P(actual < threshold) given a point forecast, assuming normal error with σ=3°F."""
    return _norm_cdf((threshold_f - temp_f) / sigma)


def norm_probability_between(temp_f: float, low_f: float, high_f: float, sigma: float = 3.0) -> float:
    """P(low <= actual < high) given a point forecast, assuming normal error with σ=3°F."""
    return _norm_cdf((high_f - temp_f) / sigma) - _norm_cdf((low_f - temp_f) / sigma)


def get_monthly_actual_precip(lat: float, lon: float, year: int, month: int, tz: str) -> float:
    """
    Return total precipitation already fallen this month (inches), from Open-Meteo archive.
    Uses a 2-day lag since archive data isn't fully available for the most recent days.
    Returns 0.0 on any failure so callers can proceed with forecast-only estimates.
    """
    month_start = date(year, month, 1)
    end_date = date.today() - timedelta(days=2)
    if end_date < month_start:
        return 0.0

    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum",
        "start_date": month_start.isoformat(),
        "end_date": end_date.isoformat(),
        "precipitation_unit": "inch",
        "timezone": tz,
    }
    for attempt in range(3):
        try:
            resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
            resp.raise_for_status()
            values = resp.json().get("daily", {}).get("precipitation_sum", [])
            return sum(v for v in values if v is not None)
        except requests.exceptions.Timeout:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
            else:
                print("  Archive API timeout after 3 attempts — assuming 0\" so far.")
                return 0.0
        except Exception as e:
            print(f"  Archive API error: {e} — assuming 0\" so far.")
            return 0.0
    return 0.0


def get_ensemble_precip_remaining(lat: float, lon: float, month_end: date, tz: str) -> list[float]:
    """
    Return total remaining-month precipitation (inches) per GFS ensemble member,
    covering today through month_end.
    """
    today = date.today()
    if today > month_end:
        return []

    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum",
        "models": "gfs_seamless",
        "start_date": today.isoformat(),
        "end_date": month_end.isoformat(),
        "precipitation_unit": "inch",
        "timezone": tz,
    }
    for attempt in range(3):
        try:
            resp = requests.get(ENSEMBLE_URL, params=params, timeout=60)
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            member_totals = []
            for key, values in daily.items():
                if key.startswith("precipitation_sum") and values:
                    member_totals.append(sum(v for v in values if v is not None))
            return member_totals
        except requests.exceptions.Timeout:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
            else:
                print("  Precip ensemble timeout after 3 attempts — skipping.")
                return []
        except Exception as e:
            print(f"  Precip ensemble error: {e} — skipping.")
            return []
    return []


def probability_precip_above(actual_so_far: float, member_totals: list[float], threshold_inches: float) -> float | None:
    """
    P(monthly total > threshold) given rain already fallen and ensemble forecasts
    for remaining days. Returns None if no ensemble data is available.
    """
    if actual_so_far > threshold_inches:
        return 1.0
    if not member_totals:
        return None
    totals = [actual_so_far + m for m in member_totals]
    return sum(1 for t in totals if t > threshold_inches) / len(totals)
