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
MAX_YES_BET_MARKET_PRICE = 0.0   # YES bets fully disabled on 2026-05-28.
                                 # Cumulative evidence over ~6 weeks: ~180 YES bets, ~3 wins, ~2% WR.
                                 # 14-day audit (May 14-28): 79 YES bets, 2 wins, -$534. The cheap
                                 # longshot band (0-5¢) is +$16 over 37 trades — statistical noise,
                                 # not a working thesis. Calibration audit shows our model is
                                 # anti-correlated with reality at every YES probability band.
                                 # Set to 0.0 (since yes_ask is always > 0, this blocks all YES
                                 # bets through the yes_market_price_too_high path).
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

# Reduced-stake city list for NO bets, added 2026-05-28. Per the 14-day P&L audit:
# Oklahoma City NO -$394, DC NO -$160, Phoenix NO -$30, Los Angeles NO -$50.
# Capping stakes at $50 instead of full ban so we keep collecting data on these cells
# in case the losses turn out to be small-sample noise.
REDUCED_STAKE_NO_CITIES = ("Oklahoma City", "DC", "Phoenix", "Los Angeles")
REDUCED_STAKE_NO_CAP_USD = 50

# Cheap-tail YES carve-out disabled on 2026-05-28. After 6 weeks of live trading, the
# asymmetric-payoff thesis has failed to produce net positive P&L: 37 cheap-longshot trades
# yielded 1 win, +$16 total (statistical noise). With YES bets fully disabled, this flag
# is also off so the suspicious-edge path can never produce a YES bet.
ALLOW_CHEAP_TAIL_YES_THROUGH_SUSPICIOUS = False
CHEAP_TAIL_YES_MAX_PRICE = 0.05  # Retained for revert; unused while the flag above is False.

# Rain bets capped at $50 (was $100) starting 2026-06-01. Rationale: May 2026
# hypothetical analysis showed +$502 / 38% ROI on the May 11-31 blocked signals
# (see project_jun01_rain_uncapped.md), with WR at 69% — borderline on the
# 70% commit threshold. Smaller stake reduces downside while we collect 1-2
# months of forward validation. Re-raise to $100 if June + July rain trading
# both deliver ≥70% WR with positive P&L.
MAX_RAIN_BET_SIZE_USD = 50

# --- Strategy switch ---
# "v1" = original logic (GFS+ECMWF ensemble member fraction + α=0.5 shrinkage).
# "v2" = distribution-fit (norm CDF around ensemble mean, σ=1.5°F, no calibration).
# Both code paths live in trader.py side-by-side; flipping the value is the rollback path.
# Each placed trade is tagged with the version that produced it (trades.strategy_version
# column) so we can attribute P&L per strategy.
#
# V2 chosen 2026-05-30 after the May 29-30 diagnostics:
#   - Bucket Brier:  V1 0.1981 (worst) → V2 0.1242 (best); 37% improvement
#   - Tail Brier:    V1 0.2053 (worst) → V2 0.0589 (best); 71% improvement
#   - Constant baseline beats V1 on both — V1 was actively miscalibrated.
# Carve-outs (YES disabled, BAN_TAIL_NO_BETS, REDUCED_STAKE_NO_CITIES, lean-YES
# bucket NO) are PRESERVED in V2 — only the probability calculation changes.
STRATEGY_VERSION = "v2"

# Forecast error std dev (°F) for V2's distribution-fit probability.
# Fit empirically on 457 settled bucket trades — sweep over σ ∈ [1, 8] showed
# σ=1.5 minimizes Brier. Per-city optimal σ ranges 1.0-2.5°F; global 1.5 captures
# most of the value. Revisit after first 200 V2 settled trades.
V2_FORECAST_SIGMA_F = 1.5

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
# Was 10 — restricted rain entries to days 1-10 of each month while we collected
# signals-only data. May 2026 retrospective analysis (project_jun01_rain_uncapped.md)
# showed the would-have-been-placed bets at 69% WR / +$502 / +38% ROI over days 11-31.
# Mechanism: market is slow to reprice contracts as month-to-date actuals accumulate,
# so the bot's "actual + ensemble remaining" probability sees gaps the market doesn't.
# Set to 99 (effectively no cutoff) to trade rain throughout the month. Combined
# with MAX_RAIN_BET_SIZE_USD = 50, downside is bounded while we collect forward data.
RAIN_MAX_ENTRY_DAY = 99

# --- Model parameters ---
FORECAST_HORIZON_DAYS = 7  # Only trade contracts resolving within 7 days
KELLY_CAP = 0.05           # Never bet more than 5% of capital on one trade
KALSHI_FEE_RATE = 0.07     # Kalshi charges 7% on net profit per winning trade
