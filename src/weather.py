import time
import requests
from datetime import date


ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


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
