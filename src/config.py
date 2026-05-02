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

# --- Kalshi API ---
KALSHI_API_KEY_ID = os.environ["KALSHI_API_KEY_ID"]   # UUID key identifier
KALSHI_API_KEY    = os.environ["KALSHI_API_KEY"]       # RSA private key (middle part only)
KALSHI_BASE_URL   = "https://trading-api.kalshi.com/trade-api/v2"

# --- Database ---
SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]

# --- Cities to monitor ---
# Kalshi settles weather contracts using official NOAA airport station readings.
TARGET_CITIES = [
    {"name": "Dallas",   "station": "KDFW", "lat": 32.8998, "lon": -97.0403, "tz": "America/Chicago"},
    {"name": "Houston",  "station": "KIAH", "lat": 29.9902, "lon": -95.3368, "tz": "America/Chicago"},
    {"name": "Chicago",  "station": "KORD", "lat": 41.9742, "lon": -87.9073, "tz": "America/Chicago"},
    {"name": "New York", "station": "KJFK", "lat": 40.6413, "lon": -73.7781, "tz": "America/New_York"},
    {"name": "Miami",    "station": "KMIA", "lat": 25.7959, "lon": -80.2870, "tz": "America/New_York"},
]

# --- Model parameters ---
FORECAST_HORIZON_DAYS = 7  # Only trade contracts resolving within 7 days
KELLY_CAP = 0.05           # Never bet more than 5% of capital on one trade
