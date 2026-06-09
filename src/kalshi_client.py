from __future__ import annotations
import base64
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from config import KALSHI_API_KEY, KALSHI_API_KEY_ID, KALSHI_BASE_URL

# The path prefix that Kalshi includes in the signature message
KALSHI_API_PATH_PREFIX = "/trade-api/v2"

# Status codes worth retrying. 403 included because Kalshi has been observed
# returning transient 403s during platform issues (e.g., 2026-06-06 outage).
# 401/404/400 are excluded — those indicate caller-side issues that won't
# resolve by retrying.
_RETRY_STATUS_CODES = frozenset({403, 408, 429, 500, 502, 503, 504})

# Backoff schedule for GET retries: 3 total attempts (1 initial + 2 retries).
# Total worst-case extra wait per call: ~20s.
_GET_RETRY_BACKOFFS_S = (5, 15)


def _load_private_key(raw: str):
    """
    Accept the RSA private key with or without PEM headers.
    Reconstructs proper PEM format if only the base64 body was stored.
    """
    raw = raw.strip().replace("\r\n", "\n")

    if raw.startswith("-----BEGIN"):
        pem = raw
    else:
        # Strip any whitespace and reformat into 64-char lines
        body = raw.replace(" ", "").replace("\n", "")
        lines = [body[i:i+64] for i in range(0, len(body), 64)]
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            + "\n".join(lines)
            + "\n-----END RSA PRIVATE KEY-----"
        )

    return serialization.load_pem_private_key(pem.encode(), password=None)


_PRIVATE_KEY = _load_private_key(KALSHI_API_KEY)


def _auth_headers(method: str, path: str) -> dict:
    """
    Generate Kalshi RSA auth headers for a single request.
    Kalshi signs: timestamp_ms + METHOD + full_path (no query string).
    The full path must include the /trade-api/v2 prefix.
    """
    ts = str(int(time.time() * 1000))
    full_path = KALSHI_API_PATH_PREFIX + path
    message = (ts + method.upper() + full_path).encode("utf-8")

    signature = _PRIVATE_KEY.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )

    return {
        "KALSHI-ACCESS-KEY":       KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
        "Content-Type":            "application/json",
    }


class KalshiClient:
    def __init__(self):
        self.base = KALSHI_BASE_URL
        self.session = requests.Session()

    def _get(self, path: str, params: dict = None) -> dict:
        """
        GET with up to 3 attempts and exponential backoff for transient errors.
        Retries on _RETRY_STATUS_CODES (403/408/429/5xx) and connection/timeout
        errors. Raises on non-retryable codes (400/401/404/etc.) or after all
        attempts fail. GET is idempotent so retries are safe.
        """
        for attempt in range(1 + len(_GET_RETRY_BACKOFFS_S)):
            try:
                resp = self.session.get(
                    self.base + path,
                    headers=_auth_headers("GET", path),
                    params=params,
                    timeout=15,
                )
                if resp.ok:
                    return resp.json()
                # Decide whether to retry this status code
                if resp.status_code in _RETRY_STATUS_CODES and attempt < len(_GET_RETRY_BACKOFFS_S):
                    wait = _GET_RETRY_BACKOFFS_S[attempt]
                    print(f"  Kalshi GET {path} returned {resp.status_code}; retrying in {wait}s "
                          f"(attempt {attempt+1}/{1 + len(_GET_RETRY_BACKOFFS_S)})")
                    time.sleep(wait)
                    continue
                # Non-retryable status code, or final attempt failed
                print(f"Kalshi API error {resp.status_code} on GET {path}: {resp.text[:200]}")
                resp.raise_for_status()
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < len(_GET_RETRY_BACKOFFS_S):
                    wait = _GET_RETRY_BACKOFFS_S[attempt]
                    print(f"  Kalshi GET {path} hit {type(e).__name__}; retrying in {wait}s "
                          f"(attempt {attempt+1}/{1 + len(_GET_RETRY_BACKOFFS_S)})")
                    time.sleep(wait)
                    continue
                raise
        # Should never reach here, but be explicit
        raise RuntimeError(f"Kalshi GET {path} exhausted all retries")

    def _post(self, path: str, payload: dict) -> dict:
        resp = self.session.post(
            self.base + path,
            headers=_auth_headers("POST", path),
            json=payload,
            timeout=15,
        )
        if not resp.ok:
            print(f"Kalshi API error {resp.status_code} on POST {path}: {resp.text}")
        resp.raise_for_status()
        return resp.json()

    def get_balance(self) -> dict:
        return self._get("/portfolio/balance")

    def get_series(self, limit: int = 200, cursor: str = None) -> dict:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._get("/series", params=params)

    def get_all_series(self) -> list[dict]:
        series, cursor = [], None
        while True:
            data = self.get_series(cursor=cursor)
            series.extend(data.get("series", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        return series

    def get_events(self, series_ticker: str = None, limit: int = 200,
                   cursor: str = None, status: str = "open") -> dict:
        """
        Fetch events for a series. After the _get retry budget is exhausted,
        return an empty events list instead of raising — this lets the calling
        cron cycle skip the failed series and continue evaluating other cities.
        Individual series failure no longer kills the whole bot run.
        """
        params = {"limit": limit, "with_nested_markets": "true"}
        if status:
            params["status"] = status
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        try:
            return self._get("/events", params=params)
        except Exception as e:
            print(f"  ⚠ Kalshi get_events FAILED for series={series_ticker} after retries: "
                  f"{type(e).__name__}: {e}")
            print(f"  → Skipping this series; the rest of the run continues.")
            return {"events": []}

    def get_all_events(self, series_ticker: str = None, status: str = "open") -> list[dict]:
        """Paginated version — fetches all events across all cursor pages."""
        events, cursor = [], None
        while True:
            data = self.get_events(series_ticker=series_ticker, cursor=cursor, status=status)
            events.extend(data.get("events", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        return events

    def get_markets_for_event(self, event_ticker: str) -> list[dict]:
        data = self._get(f"/events/{event_ticker}")
        return data.get("markets", [])

    def get_markets(self, status: str = "open", limit: int = 200, cursor: str = None) -> dict:
        params = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets", params=params)

    def get_all_open_markets(self) -> list[dict]:
        markets, cursor = [], None
        while True:
            data = self.get_markets(cursor=cursor)
            markets.extend(data.get("markets", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        return markets

    def get_market(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}").get("market", {})

    def get_orderbook(self, ticker: str) -> dict:
        """
        Fetch the order book for a market. Kalshi returns:
          { "orderbook_fp": { "yes_dollars": [["0.45", "100.00"], ...],
                              "no_dollars":  [["0.55", "50.00"],  ...] } }
        Each entry is [price_in_dollars_as_string, contract_count_as_string], sorted
        ascending by price. Returns the inner orderbook_fp dict, or {} on failure.
        """
        try:
            resp = self._get(f"/markets/{ticker}/orderbook")
            return resp.get("orderbook_fp") or resp.get("orderbook") or {}
        except Exception as e:
            print(f"  Orderbook fetch failed for {ticker}: {e}")
            return {}

    def get_liquidity_at_ask(self, ticker: str, side: str) -> tuple[float, float]:
        """
        Returns (best_ask_price_dollars, contracts_available_at_that_price) for buying
        the given side. Returns (None, 0) if there's no liquidity. The ask for buying YES
        is derived from NO bids: ask_yes = 1.00 - highest_no_bid.
        """
        ob = self.get_orderbook(ticker)
        opposing_key = "no_dollars" if side == "yes" else "yes_dollars"
        bids = ob.get(opposing_key) or []
        if not bids:
            return (None, 0)
        # Highest bid on the opposing side determines the best ask price for our side.
        # Bids are sorted ascending, so the last entry is the highest.
        best_price, best_count = bids[-1]
        ask_price = round(1.0 - float(best_price), 4)
        return (ask_price, float(best_count))

    def place_order(self, ticker: str, side: str, count: int, limit_price: int) -> dict:
        payload = {
            "ticker":      ticker,
            "side":        side,
            "type":        "limit",
            "count":       count,
            "limit_price": limit_price,
            "action":      "buy",
        }
        return self._post("/portfolio/orders", payload)
