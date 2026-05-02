import base64
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from config import KALSHI_API_KEY, KALSHI_API_KEY_ID, KALSHI_BASE_URL

# The path prefix that Kalshi includes in the signature message
KALSHI_API_PATH_PREFIX = "/trade-api/v2"


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
        resp = self.session.get(
            self.base + path,
            headers=_auth_headers("GET", path),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        resp = self.session.post(
            self.base + path,
            headers=_auth_headers("POST", path),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_balance(self) -> dict:
        return self._get("/portfolio/balance")

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
