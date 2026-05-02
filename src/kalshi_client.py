import requests
from config import KALSHI_API_KEY, KALSHI_BASE_URL


class KalshiClient:
    """
    Thin wrapper around the Kalshi v2 REST API.

    Auth note: Kalshi uses 'Authorization: Token {key}' for API key auth.
    If you get 401 errors, check the Kalshi API docs at:
    https://trading-api.kalshi.co/trade-api/v2/docs
    — the exact header format may have changed.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {KALSHI_API_KEY}",
                "Content-Type": "application/json",
            }
        )

    def get_balance(self) -> dict:
        resp = self.session.get(f"{KALSHI_BASE_URL}/portfolio/balance", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_markets(self, status: str = "open", limit: int = 200, cursor: str = None) -> dict:
        params = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        resp = self.session.get(f"{KALSHI_BASE_URL}/markets", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_all_open_markets(self) -> list[dict]:
        """Paginate through all open markets and return full list."""
        markets = []
        cursor = None
        while True:
            data = self.get_markets(cursor=cursor)
            markets.extend(data.get("markets", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        return markets

    def get_market(self, ticker: str) -> dict:
        resp = self.session.get(f"{KALSHI_BASE_URL}/markets/{ticker}", timeout=15)
        resp.raise_for_status()
        return resp.json().get("market", {})

    def get_orderbook(self, ticker: str) -> dict:
        resp = self.session.get(f"{KALSHI_BASE_URL}/markets/{ticker}/orderbook", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def place_order(self, ticker: str, side: str, count: int, limit_price: int) -> dict:
        """
        Place a limit order.
        side: 'yes' or 'no'
        count: number of contracts (each contract = $1 max payout)
        limit_price: price in cents (1–99)
        """
        payload = {
            "ticker": ticker,
            "side": side,
            "type": "limit",
            "count": count,
            "limit_price": limit_price,
            "action": "buy",
        }
        resp = self.session.post(
            f"{KALSHI_BASE_URL}/portfolio/orders", json=payload, timeout=15
        )
        resp.raise_for_status()
        return resp.json()
