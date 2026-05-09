import os

# --- Safety switch ---
# Keep this True until backtesting + 4 weeks of paper trading are complete.
# Flip to False only when you are ready to place real money orders.
PAPER_TRADING = True

# --- Capital management ---
STARTING_CAPITAL = 5000
MAX_TRADE_SIZE_USD = 100    # Hard cap per trade
DAILY_LOSS_LIMIT_USD = 150  # Bot shuts down for the day if hit
MIN_EDGE_THRESHOLD = 0.05   # Minimum 5% edge required to place any bet
MAX_EDGE_THRESHOLD = 0.55   # Edge above this is likely a model bias artifact — log but don't bet
MAX_NO_BET_YES_PRICE = 0.20 # Don't bet NO when market prices YES above this — 20-30% range lost -$246 in data
MAX_NO_BET_OUR_PROB = 0.12  # Don't bet NO when our model gives YES >12% — above this lost -$816 across 338 trades

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
    # "KXHIGHTLV": "Las Vegas",  # Disabled — consistent -$362 loss, GFS warm bias in desert heat
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
