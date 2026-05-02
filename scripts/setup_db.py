"""
One-time script to create the required tables in Supabase.
Run this once from your local machine:
  cd scripts && python setup_db.py
"""

import os
import psycopg2

conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS signals (
    id           SERIAL PRIMARY KEY,
    city         VARCHAR(50),
    ticker       VARCHAR(100),
    our_probability   DECIMAL(6,4),
    market_probability DECIMAL(6,4),
    edge         DECIMAL(6,4),
    action       VARCHAR(20),
    created_at   TIMESTAMP DEFAULT NOW()
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS trades (
    id           SERIAL PRIMARY KEY,
    ticker       VARCHAR(100),
    side         VARCHAR(5),
    amount_usd   DECIMAL(10,2),
    our_probability   DECIMAL(6,4),
    market_probability DECIMAL(6,4),
    paper_trade  BOOLEAN DEFAULT TRUE,
    settled      BOOLEAN DEFAULT FALSE,
    pnl          DECIMAL(10,2),
    created_at   TIMESTAMP DEFAULT NOW()
);
""")

conn.commit()
cur.close()
conn.close()
print("Tables created successfully.")
