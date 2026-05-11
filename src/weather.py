from __future__ import annotations
import math
import time
import requests
from datetime import date, datetime, timedelta


ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
NWS_API_BASE = "https://api.weather.gov"
NWS_HEADERS = {"User-Agent": "Lakshmera-weather-bot (devidas.desai@gmail.com)"}


def _fetch_ensemble(lat: float, lon: float, target_date: date, tz: str, model: str) -> list[float]:
    """Internal: fetch a single model's ensemble daily max temps for one date."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": model,
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
                print(f"  Open-Meteo {model} timeout (attempt {attempt+1}/3), retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  Open-Meteo {model} timeout after 3 attempts — skipping this model.")
                return []
        except Exception as e:
            print(f"  Open-Meteo {model} error: {e} — skipping this model.")
            return []


def get_ensemble_temps(lat: float, lon: float, target_date: date, tz: str) -> list[float]:
    """
    Fetch GFS-only ensemble. Preserved for backward compatibility with rain_trader.py
    and any other caller that wants pure GFS.
    """
    return _fetch_ensemble(lat, lon, target_date, tz, "gfs_seamless")


def get_blended_ensemble_temps(lat: float, lon: float, target_date: date, tz: str) -> list[float]:
    """
    Fetch GFS + ECMWF ensembles together and return as a combined list.
    ECMWF is generally regarded as the most skillful global model; GFS is a useful
    independent signal. Combining gives ~80 effective members vs. ~31 from GFS alone.
    Falls back gracefully if either model fails.
    """
    gfs   = _fetch_ensemble(lat, lon, target_date, tz, "gfs_seamless")
    ecmwf = _fetch_ensemble(lat, lon, target_date, tz, "ecmwf_ifs025")
    combined = gfs + ecmwf
    if gfs and ecmwf:
        print(f"  Ensemble blend: GFS {len(gfs)} members + ECMWF {len(ecmwf)} members = {len(combined)} total")
    elif gfs:
        print(f"  Ensemble blend: GFS {len(gfs)} members (ECMWF unavailable)")
    elif ecmwf:
        print(f"  Ensemble blend: ECMWF {len(ecmwf)} members (GFS unavailable)")
    return combined


# Module-level cache so climatology and NWS forecast aren't re-fetched within a single run
_climatology_cache: dict[tuple, list[float]] = {}
_nws_forecast_cache: dict[tuple, dict[date, float]] = {}


def get_climatology_temps(lat: float, lon: float, target_date: date, tz: str,
                          years_back: int = 5, window_days: int = 7) -> list[float]:
    """
    Return historical daily-max temperatures for the same day-of-year (±window_days),
    across the last `years_back` years. Used for city/seasonal base rates.
    Cached per (lat, lon, target_date) within a single process so multiple thresholds
    on the same (city, date) only fetch once.
    """
    key = (round(lat, 4), round(lon, 4), target_date)
    if key in _climatology_cache:
        return _climatology_cache[key]

    all_temps: list[float] = []
    today = date.today()
    for y in range(today.year - years_back, today.year):
        try:
            center = date(y, target_date.month, target_date.day)
        except ValueError:
            continue  # e.g., Feb 29 in non-leap year
        ws = center - timedelta(days=window_days)
        we = center + timedelta(days=window_days)
        params = {
            "latitude": lat, "longitude": lon,
            "daily": "temperature_2m_max",
            "start_date": ws.isoformat(), "end_date": we.isoformat(),
            "temperature_unit": "fahrenheit", "timezone": tz,
        }
        try:
            resp = requests.get(ARCHIVE_URL, params=params, timeout=30)
            resp.raise_for_status()
            temps = resp.json().get("daily", {}).get("temperature_2m_max", [])
            all_temps.extend(t for t in temps if t is not None)
        except Exception as e:
            print(f"  Climatology fetch error for {y}: {e}")
            continue

    _climatology_cache[key] = all_temps
    return all_temps


def climatology_base_rate(climatology: list[float], threshold_f: float, direction: str,
                          low_f: float = None, high_f: float = None) -> float | None:
    """
    Compute the historical exceedance rate for a given contract criterion.
    Returns None if climatology is empty.
    """
    if not climatology:
        return None
    n = len(climatology)
    if direction == "above":
        return sum(1 for t in climatology if t > threshold_f) / n
    elif direction == "below":
        return sum(1 for t in climatology if t < threshold_f) / n
    elif direction == "bucket" and low_f is not None and high_f is not None:
        return sum(1 for t in climatology if low_f <= t < high_f) / n
    return None


def get_nws_forecast_temps(lat: float, lon: float) -> dict[date, float]:
    """
    Fetch the local National Weather Service forecast (which is based on NBM +
    local forecaster expertise — i.e., the "official" US prediction).
    Returns {date: max_temp_f, ...} for the next ~7 days, or {} on failure.

    Two-step API: first resolve lat/lon to a forecast grid, then pull the forecast.
    Cached per (lat, lon) for the lifetime of the process.
    """
    key = (round(lat, 4), round(lon, 4))
    if key in _nws_forecast_cache:
        return _nws_forecast_cache[key]

    try:
        # Step 1: lat/lon → grid
        url = f"{NWS_API_BASE}/points/{lat:.4f},{lon:.4f}"
        resp = requests.get(url, headers=NWS_HEADERS, timeout=10)
        resp.raise_for_status()
        forecast_url = resp.json()["properties"]["forecast"]

        # Step 2: pull periods
        resp = requests.get(forecast_url, headers=NWS_HEADERS, timeout=10)
        resp.raise_for_status()
        periods = resp.json()["properties"]["periods"]

        out: dict[date, float] = {}
        for p in periods:
            if not p.get("isDaytime", False):
                continue
            iso = p["startTime"].replace("Z", "+00:00")
            d = datetime.fromisoformat(iso).date()
            out[d] = float(p["temperature"])

        _nws_forecast_cache[key] = out
        return out
    except Exception as e:
        print(f"  NWS forecast error: {e}")
        _nws_forecast_cache[key] = {}
        return {}


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
