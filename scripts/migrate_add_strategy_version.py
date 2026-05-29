"""
Adds the strategy_version column to the trades table.
Default 'v1' for all existing rows so historical attribution is preserved.

Run after: src/database.py log_trade() updated to write strategy_version.
"""
import os
import psycopg2

SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]

conn = psycopg2.connect(SUPABASE_DB_URL)
cur = conn.cursor()

cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_version TEXT DEFAULT 'v1';")
cur.execute("UPDATE trades SET strategy_version = 'v1' WHERE strategy_version IS NULL;")

conn.commit()

cur.execute("SELECT strategy_version, COUNT(*) FROM trades GROUP BY strategy_version ORDER BY 1;")
print("strategy_version column added. Current distribution:")
for sv, n in cur.fetchall():
    print(f"  {sv!r}: {n} rows")

cur.close()
conn.close()
