import os
import psycopg2

SUPABASE_DB_URL = os.environ["SUPABASE_DB_URL"]

conn = psycopg2.connect(SUPABASE_DB_URL)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS backtest_trades (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    city TEXT,
    target_date DATE,
    side TEXT,
    our_probability NUMERIC,
    market_probability NUMERIC,
    edge NUMERIC,
    action TEXT NOT NULL,
    contract_count INT,
    price_paid NUMERIC,
    result TEXT,
    pnl NUMERIC,
    created_at TIMESTAMP DEFAULT NOW()
);
""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_backtest_run_id ON backtest_trades(run_id);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_backtest_target_date ON backtest_trades(target_date);")

conn.commit()
cur.close()
conn.close()
print("backtest_trades table created (or already exists).")
