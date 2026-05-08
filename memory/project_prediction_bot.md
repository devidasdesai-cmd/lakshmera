---
name: Project - Prediction Market Bot
description: Kalshi weather trading bot project details, stack, and decisions made
type: project
---

Building a weather prediction market trading bot on Kalshi.

**Stack (all free):** GitHub Actions (scheduler), Supabase (database), NOAA API + Open-Meteo (weather data), Python.

**Repo:** Private GitHub repo named `Lakshmera` — already exists locally at `/Users/devidasdesai/Downloads/MY WORLD/DD/Coding Projects/Lakshmera`. GitHub username: `devidasdesai-cmd`.

**Capital:** $5,000 starting. Max 2% per trade (~$100), typical $25–$75 per contract initially.

**Primary markets:** Kalshi daily high temperature series for 13 US cities. Dallas (KDFW) is priority due to user's local knowledge.

**Kalshi API:** Production account. Uses RSA-PSS signing with KALSHI_API_KEY (full PEM) + KALSHI_API_KEY_ID (UUID). Base URL: api.elections.kalshi.com. Settles against NWS Daily Climate Reports.

**Settlement stations (verified):**
- Dallas: KDFW (32.8968, -97.0379)
- Houston: KHOU Hobby Airport (29.6458, -95.2772) — NOT Intercontinental
- New York: KNYC Central Park (40.7790, -73.9692) — NOT JFK
- Boston: KBOS (42.3631, -71.0064)
- Minneapolis: KMSP (44.8822, -93.2218)
- Los Angeles: KLAX (33.9425, -118.4081)
- Phoenix: KPHX (33.4343, -112.0116)
- DC: KDCA (38.8513, -77.0360)
- Las Vegas: KLAS (36.0803, -115.1524)
- Seattle: KSEA (47.4499, -122.3118)
- San Antonio: KSAT (29.5337, -98.4698)
- San Francisco: KSFO (37.6196, -122.3656)
- Oklahoma City: KOKC (35.3931, -97.6008)

**Model plan:** Layer 1 = GFS ensemble probability (Open-Meteo). Layer 2 = historical bias correction (planned). Layer 3 = edge filter (only bet when gap > 5%). ML (XGBoost) planned for month 3+.

**TODO after core bot is live:** Add monthly GitHub Actions job to verify Kalshi settlement stations haven't changed — compare series resolution rules against config.py and alert on mismatch.

**Status (as of 2026-05-02):** Bot is functional in paper trading mode. Auth working, 60 weather markets fetched, ensemble data caching implemented. Supabase logging working. Next step: confirm full clean run with signals logged to DB.
