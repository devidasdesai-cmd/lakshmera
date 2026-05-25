import os

# --- Safety switch ---
# Keep this True until backtesting + 4 weeks of paper trading are complete.
# Flip to False only when you are ready to place real money orders.
PAPER_TRADING = True

# --- Capital management ---
STARTING_CAPITAL = 15000    # Deployable paper capital. Up from $5K based on user direction.
MAX_TRADE_SIZE_USD = 300    # Absolute ceiling per bet. Per-tier caps (see model.compute_stake_cap)
                            # narrow this further for less-profitable bet categories.
DAILY_LOSS_LIMIT_USD = 450  # Scales 3x with stake size raise (was 150 at $100 max stake).
MIN_EDGE_THRESHOLD = 0.05   # Minimum 5% edge required to place any bet
MAX_EDGE_THRESHOLD = 0.55   # Edge above this is "suspicious"; usually blocked but see exception below.
MAX_NO_BET_YES_PRICE = 0.20 # Don't bet NO when market prices YES above this.
MAX_YES_BET_MARKET_PRICE = 0.05  # Don't bet YES when market prices YES above this.
                                 # Lowered from 0.20 on 2026-05-22 after 0/53 YES wins post-May-15:
                                 # 5-20¢ band lost -$436 (0/20), 0-5¢ band lost -$98 (0/16). The
                                 # 5-20¢ band requires >10% true hit rate to break even and we are
                                 # nowhere near; only cheap longshots remain alive on asymmetric-payoff
                                 # thesis.
# (Removed MAX_NO_BET_OUR_PROB: calibration now corrects model overconfidence at the source,
#  so the redundant safety rule was blocking our best-performing NO bet category.)

# Tail-NO bets historically lost -$658 across 38 trades despite 65.8% WR — the bet structure
# requires ~70%+ WR to break even, and our model can't reliably hit that on tail NO contracts.
# Toggle to disable; mirrors the Bucket YES ban.
BAN_TAIL_NO_BETS = True

# Carve-out from MAX_NO_BET_YES_PRICE for bucket NO bets when the market mildly leans YES
# (50-65¢). NO_BET signal analysis over May 14-23 found 10 settled bucket NO blocks in this
# band with 80% WR (+$589 hypothetical P&L). Wins concentrated in desert/coastal cities
# (Las Vegas 4-0, Phoenix 2-2, LA/Houston 1-0 each). Shipping with default $100 stake to
# gather forward data; raise stake only if pattern validates over next 2 weeks.
ALLOW_BUCKET_NO_IN_LEAN_YES_ZONE = True
LEAN_YES_ZONE_MIN = 0.50
LEAN_YES_ZONE_MAX = 0.65

# Allow YES bets at very cheap prices to bypass the MAX_EDGE_THRESHOLD "suspicious" cap.
# Historical signal analysis: 22 blocked YES bets at <5¢ market price had +$29K hypothetical
# P&L from asymmetric-payoff longshots concentrated in desert cities.
ALLOW_CHEAP_TAIL_YES_THROUGH_SUSPICIOUS = True
CHEAP_TAIL_YES_MAX_PRICE = 0.05  # Only bypass if market YES ≤ 5¢

# Rain bets stay at base $100 stake; no settled rain data yet to size up confidently.
MAX_RAIN_BET_SIZE_USD = 100

# --- Probability calibration ---
# Raw GFS-derived probabilities are systematically miscalibrated. From 338 settled trades:
# when raw_prob = 0-5%, actual YES rate is ~22%. When raw_prob = 70%+, actual is ~25%.
# The market is well-calibrated; our model is not. Shrinking toward the empirical base
# rate corrects for this before computing edge.
# Set CALIBRATION_ALPHA = 1.0 to disable (no shrinkage, raw probabilities used directly).
CALIBRATION_ALPHA = 0.5      # Returned to the original 2026-05-10 calibration value after
                             # raising it to 0.85 on 2026-05-14 made YES bets worse, not better.
                             # 0/53 YES wins since May 15 confirmed the model is structurally
                             # overconfident on tail YES at every probability band (65-75%, 50-60%,
                             # 30-50%, <30% — all 0% actual). Shrinking aggressively toward the
                             # 0.25 base rate is the correct response; the May 14 raise was solving
                             # the wrong problem.
TEMPERATURE_BASE_RATE = 0.25  # used when city-specific climatology is unavailable

# --- Correlated bet management ---
# Bot was placing 3-6 bets per (city, date) on the same underlying outcome (the day's high
# temperature), which compounds variance without adding edge. Cap at one bet per (city, date)
# — the highest-edge contract wins.
ONE_BET_PER_CITY_DATE = True

# --- Multi-source forecast data (added 2026-05-10) ---
# ECMWF ensemble blend: combines GFS + ECMWF ensembles into one ~80-member super-ensemble.
# ECMWF is generally considered the most skillful global model.
USE_ECMWF_BLEND = True

# Climatology base rate: use 5 years of historical actuals (±7 days, same day-of-year) as
# the city-specific base rate for calibration, instead of a flat 0.25.
USE_CLIMATOLOGY_BASE_RATE = True

# NWS forecast logging: pull NWS local forecast (NBM-derived) and log it alongside our
# prediction for sanity checking. Currently informational only; not used in betting math.
LOG_NWS_FORECAST = True

# Kalshi order book logging: fetch liquidity at the ask before each paper bet. Logged for
# diagnostic purposes; in live trading we'd use this to adjust fill expectations.
LOG_ORDERBOOK = True

# --- Kalshi API ---
KALSHI_API_KEY_ID = os.environ["KALSHI_API_KEY_ID"]
KALSHI_API_KEY    = os.environ["KALSHI_API_KEY"]
KALSHI_BASE_URL   = "https://api.elections.kalshi.com/trade-api/v2"

# --- Database ---
SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]

# --- Cities to monitor ---
# Coordinates match the exact NOAA station Kalshi uses to settle each contract.
# Settlements are based on the NWS Daily Climate Report (CLI), not real-time data.
# Sources verified against Kalshi help center and Wethr.net market index.
TARGET_CITIES = [
    {"name": "Dallas",       "station": "KDFW", "lat": 32.8968, "lon": -97.0379,  "tz": "America/Chicago"},
    {"name": "Houston",      "station": "KHOU", "lat": 29.6458, "lon": -95.2772,  "tz": "America/Chicago"},   # Hobby Airport, NOT Intercontinental
    {"name": "New York",     "station": "KNYC", "lat": 40.7790, "lon": -73.9692,  "tz": "America/New_York"},  # Central Park, NOT JFK
    {"name": "Boston",       "station": "KBOS", "lat": 42.3631, "lon": -71.0064,  "tz": "America/New_York"},
    {"name": "Minneapolis",  "station": "KMSP", "lat": 44.8822, "lon": -93.2218,  "tz": "America/Chicago"},
    {"name": "Los Angeles",  "station": "KLAX", "lat": 33.9425, "lon": -118.4081, "tz": "America/Los_Angeles"},
    {"name": "Phoenix",      "station": "KPHX", "lat": 33.4343, "lon": -112.0116, "tz": "America/Phoenix"},
    {"name": "DC",           "station": "KDCA", "lat": 38.8513, "lon": -77.0360,  "tz": "America/New_York"},
    {"name": "Las Vegas",    "station": "KLAS", "lat": 36.0803, "lon": -115.1524, "tz": "America/Los_Angeles"},
    {"name": "Seattle",      "station": "KSEA", "lat": 47.4499, "lon": -122.3118, "tz": "America/Los_Angeles"},
    {"name": "San Antonio",  "station": "KSAT", "lat": 29.5337, "lon": -98.4698,  "tz": "America/Chicago"},
    {"name": "San Francisco","station": "KSFO", "lat": 37.6196, "lon": -122.3656, "tz": "America/Los_Angeles"},
    {"name": "Oklahoma City","station": "KOKC", "lat": 35.3931, "lon": -97.6008,  "tz": "America/Chicago"},
    # Rain-market cities (not traded for temperature)
    {"name": "Chicago",      "station": "KORD", "lat": 41.9742, "lon": -87.9073,  "tz": "America/Chicago"},
    {"name": "Miami",        "station": "KMIA", "lat": 25.7959, "lon": -80.2870,  "tz": "America/New_York"},
    {"name": "Denver",       "station": "KDEN", "lat": 39.8561, "lon": -104.6737, "tz": "America/Denver"},
    {"name": "Austin",       "station": "KAUS", "lat": 30.1975, "lon": -97.6664,  "tz": "America/Chicago"},
    {"name": "New Orleans",  "station": "KMSY", "lat": 29.9934, "lon": -90.2580,  "tz": "America/Chicago"},
]

# --- Kalshi series → city mapping ---
# Each series ticker maps to a city name in TARGET_CITIES above.
SERIES_TO_CITY = {
    "KXHIGHTDAL":  "Dallas",
    "KXHIGHTHOU":  "Houston",
    "KXHIGHNY":    "New York",
    "KXHIGHNY0":   "New York",
    "KXHIGHTBOS":  "Boston",
    "KXHIGHTMIN":  "Minneapolis",
    "KXHIGHLAX":   "Los Angeles",
    "KXHIGHTPHX":  "Phoenix",
    "KXHIGHTDC":   "DC",
    "KXHIGHTLV":   "Las Vegas",  # Re-enabled 2026-05-10 to see if calibration+climatology
                                  # correct for the previous warm-bias losses
    "KXHIGHTSEA":  "Seattle",
    "KXHIGHTSATX": "San Antonio",
    "KXHIGHTSFO":  "San Francisco",
    "KXHIGHTOKC":  "Oklahoma City",
}

# Series we actively fetch and trade (temperature)
TARGET_SERIES = list(SERIES_TO_CITY.keys())

# --- Rain market series → city mapping ---
RAIN_SERIES_TO_CITY = {
    "KXRAINDALM":  "Dallas",
    "KXRAINHOUM":  "Houston",
    "KXRAINCHIM":  "Chicago",
    "KXRAINSEAM":  "Seattle",
    "KXRAINLAXM":  "Los Angeles",
    "KXRAINSFOM":  "San Francisco",
    "KXRAINMIAM":  "Miami",
    "KXRAINNYCM":  "New York",
    "KXRAINDENM":  "Denver",
    "KXRAINAUSM":  "Austin",
    "KXRAINNO":    "New Orleans",
}

RAIN_TARGET_SERIES = list(RAIN_SERIES_TO_CITY.keys())
RAIN_MAX_ENTRY_DAY = 10  # Don't enter monthly rain contracts after day 10 of the month

# --- Model parameters ---
FORECAST_HORIZON_DAYS = 7  # Only trade contracts resolving within 7 days
KELLY_CAP = 0.05           # Never bet more than 5% of capital on one trade
KALSHI_FEE_RATE = 0.07     # Kalshi charges 7% on net profit per winning trade
