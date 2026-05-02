"""
One-time migration: adds contract_count, price_paid, and result columns
to the trades table in your existing Supabase database.

Run once from your local machine:
  SUPABASE_DB_URL="..." python scripts/migrate_add_settlement_columns.py
"""

import os
import psycopg2

conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
cur = conn.cursor()

cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS contract_count INTEGER;")
cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS price_paid DECIMAL(6,4);")
cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS result VARCHAR(5);")

conn.commit()
cur.close()
conn.close()
print("Migration complete: contract_count, price_paid, result columns added to trades.")
