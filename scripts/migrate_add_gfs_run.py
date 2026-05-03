import os
import psycopg2

SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]

conn = psycopg2.connect(SUPABASE_DB_URL)
cur = conn.cursor()

cur.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS gfs_run TEXT;")

conn.commit()
cur.close()
conn.close()
print("gfs_run column added to trades table.")
