import psycopg2
from config import SUPABASE_DB_URL


def get_connection():
    return psycopg2.connect(SUPABASE_DB_URL)


def log_signal(city, ticker, our_prob, market_prob, edge, action):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO signals (city, ticker, our_probability, market_probability, edge, action)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (city, ticker, our_prob, market_prob, edge, action),
    )
    conn.commit()
    cur.close()
    conn.close()


def log_trade(ticker, side, amount_usd, contract_count, price_paid, our_prob, market_prob, paper_trade, gfs_run=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO trades
          (ticker, side, amount_usd, contract_count, price_paid,
           our_probability, market_probability, paper_trade, gfs_run)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (ticker, side, amount_usd, contract_count, price_paid, our_prob, market_prob, paper_trade, gfs_run),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_open_tickers(paper_trade: bool = True) -> set:
    """Return the set of tickers that already have an unsettled open position."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT ticker FROM trades WHERE settled = FALSE AND paper_trade = %s",
        (paper_trade,)
    )
    tickers = {row[0] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return tickers


def get_daily_realized_loss():
    """Sum of losses on settled trades today (real trades only)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(pnl), 0)
        FROM trades
        WHERE paper_trade = FALSE
          AND settled = TRUE
          AND pnl < 0
          AND DATE(created_at) = CURRENT_DATE
        """
    )
    loss = abs(cur.fetchone()[0])
    cur.close()
    conn.close()
    return loss
