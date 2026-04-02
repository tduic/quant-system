"""Coinbase Advanced Trade REST API client.

Handles authentication (HMAC-SHA256), order placement, cancellation,
and account queries. Includes rate limiting and retry logic.

Usage:
    client = CoinbaseRESTClient.from_env()
    result = client.place_order(symbol="BTC-USD", side="buy", size="0.001")
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx

from quant_core.rate_limiter import RateLimiter, RetryPolicy

logger = logging.getLogger(__name__)

# Coinbase Advanced Trade API
BASE_URL = "https://api.coinbase.com"

# Rate limits: 10 requests/second for private endpoints
DEFAULT_RATE_LIMIT = 10.0


class CoinbaseAuthError(Exception):
    """Raised when API credentials are missing or invalid."""


class CoinbaseAPIError(Exception):
    """Raised when the Coinbase API returns an error."""

    def __init__(self, status_code: int, message: str, response: dict | None = None):
        self.status_code = status_code
        self.response = response
        super().__init__(f"Coinbase API error {status_code}: {message}")


class CoinbaseRESTClient:
    """Authenticated Coinbase Advanced Trade REST client."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = BASE_URL,
        rate_limit: float = DEFAULT_RATE_LIMIT,
    ) -> None:
        if not api_key or not api_secret:
            msg = "Coinbase API key and secret are required"
            raise CoinbaseAuthError(msg)

        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30.0)
        self._limiter = RateLimiter(calls_per_second=rate_limit)
        self._retry = RetryPolicy(max_retries=3, base_delay=0.5)

        # Never log the secret
        logger.info("Coinbase REST client initialized (key=%s...)", api_key[:8])

    @classmethod
    def from_env(cls) -> CoinbaseRESTClient:
        """Create client from environment variables."""
        api_key = os.getenv("COINBASE_API_KEY", "")
        api_secret = os.getenv("COINBASE_API_SECRET", "")
        if not api_key or not api_secret:
            msg = "COINBASE_API_KEY and COINBASE_API_SECRET environment variables are required"
            raise CoinbaseAuthError(msg)
        return cls(api_key=api_key, api_secret=api_secret)

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """Generate HMAC-SHA256 signature for Coinbase Advanced Trade API."""
        message = f"{timestamp}{method.upper()}{path}{body}"
        return hmac.new(
            self._api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """Build authenticated request headers."""
        timestamp = str(int(time.time()))
        signature = self._sign(timestamp, method, path, body)
        return {
            "CB-ACCESS-KEY": self._api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request with rate limiting and retry."""
        body_str = json.dumps(body) if body else ""

        for attempt in range(self._retry.max_retries + 1):
            self._limiter.acquire()

            headers = self._headers(method, path, body_str)
            url = f"{self._base_url}{path}"

            try:
                if method == "GET":
                    response = self._client.get(url, headers=headers)
                elif method == "POST":
                    response = self._client.post(url, headers=headers, content=body_str)
                elif method == "DELETE":
                    response = self._client.delete(url, headers=headers)
                else:
                    msg = f"Unsupported method: {method}"
                    raise ValueError(msg)

                if response.status_code == 200:
                    return response.json()

                if self._retry.should_retry(attempt, response.status_code):
                    delay = self._retry.delay_for_attempt(attempt)
                    logger.warning(
                        "Coinbase API %s %s returned %d, retrying in %.1fs (attempt %d/%d)",
                        method,
                        path,
                        response.status_code,
                        delay,
                        attempt + 1,
                        self._retry.max_retries,
                    )
                    time.sleep(delay)
                    continue

                raise CoinbaseAPIError(
                    status_code=response.status_code,
                    message=response.text,
                    response=response.json()
                    if response.headers.get("content-type", "").startswith("application/json")
                    else None,
                )

            except httpx.HTTPError as e:
                if self._retry.should_retry(attempt):
                    delay = self._retry.delay_for_attempt(attempt)
                    logger.warning("HTTP error %s, retrying in %.1fs", e, delay)
                    time.sleep(delay)
                    continue
                msg = f"Max retries exceeded for {method} {path}"
                raise CoinbaseAPIError(status_code=0, message=msg) from e

        msg = f"Max retries exceeded for {method} {path}"
        raise CoinbaseAPIError(status_code=0, message=msg)

    # --- Public API methods ---

    def get_accounts(self) -> dict:
        """List trading accounts and balances."""
        return self._request("GET", "/api/v3/brokerage/accounts")

    def get_account(self, account_id: str) -> dict:
        """Get a specific account by ID."""
        return self._request("GET", f"/api/v3/brokerage/accounts/{account_id}")

    def place_order(
        self,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        limit_price: str | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """Place an order on Coinbase.

        Args:
            symbol: Product ID (e.g., "BTC-USD")
            side: "buy" or "sell"
            size: Order size as string
            order_type: "market" or "limit"
            limit_price: Required for limit orders
            client_order_id: Optional client-side order ID
        """
        import uuid

        # Normalize symbol: "BTCUSD" -> "BTC-USD"
        if "-" not in symbol:
            # Insert dash before last 3 chars (USD)
            symbol = f"{symbol[:-3]}-{symbol[-3:]}"

        body: dict[str, Any] = {
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "product_id": symbol,
            "side": side.upper(),
        }

        if order_type == "market":
            body["order_configuration"] = {
                "market_market_ioc": {"base_size": size},
            }
        elif order_type == "limit":
            if not limit_price:
                msg = "limit_price required for limit orders"
                raise ValueError(msg)
            body["order_configuration"] = {
                "limit_limit_gtc": {
                    "base_size": size,
                    "limit_price": limit_price,
                },
            }

        logger.info("Placing %s order: %s %s %s", order_type, side, size, symbol)
        return self._request("POST", "/api/v3/brokerage/orders", body)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an order by its exchange order ID."""
        body = {"order_ids": [order_id]}
        return self._request("POST", "/api/v3/brokerage/orders/batch_cancel", body)

    def get_order(self, order_id: str) -> dict:
        """Get order details by exchange order ID."""
        return self._request("GET", f"/api/v3/brokerage/orders/historical/{order_id}")

    def list_orders(self, product_id: str | None = None, status: str | None = None) -> dict:
        """List orders with optional filters."""
        path = "/api/v3/brokerage/orders/historical/batch"
        params = []
        if product_id:
            params.append(f"product_id={product_id}")
        if status:
            params.append(f"order_status={status}")
        if params:
            path += "?" + "&".join(params)
        return self._request("GET", path)

    def get_product(self, product_id: str) -> dict:
        """Get product details (tick size, min order, etc.)."""
        return self._request("GET", f"/api/v3/brokerage/products/{product_id}")
