"""Unit tests for Coinbase REST API client.

Tests cover authentication, signing, rate limiting, retry logic,
and all public API methods.

Test Coverage:
- Constructor validation: Requires API key and secret (CoinbaseAuthError)
- from_env() class method: Creates client from COINBASE_API_KEY and COINBASE_API_SECRET env vars
- Signing: HMAC-SHA256 signatures with consistent output for identical inputs
- Headers: Includes CB-ACCESS-KEY, CB-ACCESS-SIGN, CB-ACCESS-TIMESTAMP, Content-Type
- place_order(): Symbol normalization (BTCUSD → BTC-USD), market/limit order structures
- cancel_order(): Correct endpoint and body structure with order_ids list
- get_order(), list_orders(), get_accounts(), get_product(): Correct endpoints and parameters
- Retry logic: Retries on 5xx and 429 status codes, no retry on 4xx (except 429)
- Rate limiting: acquire() called before each request and on retries
- HTTP methods: GET, POST, DELETE used correctly
- Base URL: Trailing slashes stripped, custom URLs supported
- Error handling: HTTPError triggers retries, CoinbaseAPIError includes status and response
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

from quant_core.coinbase_rest import (
    CoinbaseAPIError,
    CoinbaseAuthError,
    CoinbaseRESTClient,
)


class TestCoinbaseAuthError(unittest.TestCase):
    """Tests for CoinbaseAuthError exception."""

    def test_raises_on_empty_api_key(self):
        """Constructor raises CoinbaseAuthError if api_key is empty."""
        with pytest.raises(CoinbaseAuthError):
            CoinbaseRESTClient(api_key="", api_secret="valid_secret")

    def test_raises_on_empty_api_secret(self):
        """Constructor raises CoinbaseAuthError if api_secret is empty."""
        with pytest.raises(CoinbaseAuthError):
            CoinbaseRESTClient(api_key="valid_key", api_secret="")

    def test_raises_on_both_empty(self):
        """Constructor raises CoinbaseAuthError if both key and secret are empty."""
        with pytest.raises(CoinbaseAuthError):
            CoinbaseRESTClient(api_key="", api_secret="")


class TestFromEnv(unittest.TestCase):
    """Tests for from_env() class method."""

    def test_from_env_raises_without_api_key(self):
        """from_env() raises CoinbaseAuthError without COINBASE_API_KEY."""
        with patch.dict(os.environ, {"COINBASE_API_SECRET": "secret"}, clear=True), pytest.raises(CoinbaseAuthError):
            CoinbaseRESTClient.from_env()

    def test_from_env_raises_without_api_secret(self):
        """from_env() raises CoinbaseAuthError without COINBASE_API_SECRET."""
        with patch.dict(os.environ, {"COINBASE_API_KEY": "key"}, clear=True), pytest.raises(CoinbaseAuthError):
            CoinbaseRESTClient.from_env()

    def test_from_env_raises_without_both(self):
        """from_env() raises CoinbaseAuthError without both env vars."""
        with patch.dict(os.environ, {}, clear=True), pytest.raises(CoinbaseAuthError):
            CoinbaseRESTClient.from_env()

    def test_from_env_succeeds_with_correct_vars(self):
        """from_env() succeeds with correct environment variables."""
        env_vars = {
            "COINBASE_API_KEY": "test_key_12345678",
            "COINBASE_API_SECRET": "test_secret_abcdefgh",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            client = CoinbaseRESTClient.from_env()
            assert client._api_key == "test_key_12345678"
            assert client._api_secret == "test_secret_abcdefgh"


class TestSigningAndHeaders(unittest.TestCase):
    """Tests for request signing and header generation."""

    def setUp(self):
        """Set up test client."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )

    def test_sign_produces_valid_hmac(self):
        """_sign() produces correct HMAC-SHA256 signature."""
        timestamp = "1234567890"
        method = "POST"
        path = "/api/v3/brokerage/orders"
        body = '{"product_id": "BTC-USD"}'

        signature = self.client._sign(timestamp, method, path, body)

        # Compute expected signature
        message = f"{timestamp}{method}{path}{body}"
        expected = hmac.new(
            self.client._api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        assert signature == expected

    def test_sign_with_empty_body(self):
        """_sign() works with empty body."""
        timestamp = "1234567890"
        method = "GET"
        path = "/api/v3/brokerage/accounts"

        signature = self.client._sign(timestamp, method, path, "")

        message = f"{timestamp}{method}{path}"
        expected = hmac.new(
            self.client._api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        assert signature == expected

    @patch("quant_core.coinbase_rest.time.time")
    def test_headers_includes_required_fields(self, mock_time):
        """_headers() includes CB-ACCESS-KEY, CB-ACCESS-SIGN, CB-ACCESS-TIMESTAMP."""
        mock_time.return_value = 1234567890

        headers = self.client._headers("GET", "/api/v3/brokerage/accounts", "")

        assert "CB-ACCESS-KEY" in headers
        assert "CB-ACCESS-SIGN" in headers
        assert "CB-ACCESS-TIMESTAMP" in headers
        assert "Content-Type" in headers
        assert headers["CB-ACCESS-KEY"] == "test_key"
        assert headers["CB-ACCESS-TIMESTAMP"] == "1234567890"
        assert headers["Content-Type"] == "application/json"

    @patch("quant_core.coinbase_rest.time.time")
    def test_headers_signature_is_valid(self, mock_time):
        """_headers() signature is correctly computed."""
        mock_time.return_value = 1234567890
        method = "POST"
        path = "/api/v3/brokerage/orders"
        body = '{"product_id": "BTC-USD"}'

        headers = self.client._headers(method, path, body)

        # Verify signature matches what we'd compute manually
        expected_sig = self.client._sign("1234567890", method, path, body)
        assert headers["CB-ACCESS-SIGN"] == expected_sig


class TestPlaceOrder(unittest.TestCase):
    """Tests for place_order() method."""

    def setUp(self):
        """Set up test client with mocked HTTP client."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    def test_place_order_normalizes_symbol(self):
        """place_order normalizes symbol: 'BTCUSD' → 'BTC-USD'."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_id": "12345"}
        self.client._client.post.return_value = response

        self.client.place_order(
            symbol="BTCUSD",
            side="buy",
            size="0.001",
        )

        # Check that the request was made with normalized symbol
        call_args = self.client._client.post.call_args
        body_str = call_args[1]["content"]
        body = json.loads(body_str)
        assert body["product_id"] == "BTC-USD"

    def test_place_order_with_market_order(self):
        """place_order with market order builds correct body with market_market_ioc."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_id": "12345"}
        self.client._client.post.return_value = response

        self.client.place_order(
            symbol="BTC-USD",
            side="buy",
            size="0.001",
            order_type="market",
        )

        call_args = self.client._client.post.call_args
        body_str = call_args[1]["content"]
        body = json.loads(body_str)

        assert body["order_configuration"]["market_market_ioc"]["base_size"] == "0.001"
        assert "limit_limit_gtc" not in body["order_configuration"]

    def test_place_order_with_limit_order(self):
        """place_order with limit order builds correct body with limit_limit_gtc."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_id": "12345"}
        self.client._client.post.return_value = response

        self.client.place_order(
            symbol="BTC-USD",
            side="sell",
            size="0.5",
            order_type="limit",
            limit_price="45000.50",
        )

        call_args = self.client._client.post.call_args
        body_str = call_args[1]["content"]
        body = json.loads(body_str)

        assert body["order_configuration"]["limit_limit_gtc"]["base_size"] == "0.5"
        assert body["order_configuration"]["limit_limit_gtc"]["limit_price"] == "45000.50"
        assert "market_market_ioc" not in body["order_configuration"]

    def test_place_order_raises_on_limit_without_price(self):
        """place_order raises ValueError for limit order without limit_price."""
        with pytest.raises(ValueError, match="limit_price required"):
            self.client.place_order(
                symbol="BTC-USD",
                side="buy",
                size="0.001",
                order_type="limit",
            )

    def test_place_order_includes_side(self):
        """place_order request includes side field."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_id": "12345"}
        self.client._client.post.return_value = response

        self.client.place_order(
            symbol="BTC-USD",
            side="buy",
            size="0.001",
        )

        call_args = self.client._client.post.call_args
        body_str = call_args[1]["content"]
        body = json.loads(body_str)
        assert body["side"] == "BUY"

    def test_place_order_includes_client_order_id(self):
        """place_order request includes client_order_id."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_id": "12345"}
        self.client._client.post.return_value = response

        custom_id = "my_custom_order_id"
        self.client.place_order(
            symbol="BTC-USD",
            side="buy",
            size="0.001",
            client_order_id=custom_id,
        )

        call_args = self.client._client.post.call_args
        body_str = call_args[1]["content"]
        body = json.loads(body_str)
        assert body["client_order_id"] == custom_id

    def test_place_order_generates_uuid_if_no_client_id(self):
        """place_order generates UUID for client_order_id if not provided."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_id": "12345"}
        self.client._client.post.return_value = response

        self.client.place_order(
            symbol="BTC-USD",
            side="buy",
            size="0.001",
        )

        call_args = self.client._client.post.call_args
        body_str = call_args[1]["content"]
        body = json.loads(body_str)

        # Should have a non-empty client_order_id that looks like a UUID
        assert "client_order_id" in body
        assert len(body["client_order_id"]) > 0
        assert "-" in body["client_order_id"]  # UUID format includes dashes


class TestCancelOrder(unittest.TestCase):
    """Tests for cancel_order() method."""

    def setUp(self):
        """Set up test client with mocked HTTP client."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    def test_cancel_order_sends_order_ids_payload(self):
        """cancel_order sends correct order_ids payload."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_ids": ["order_123"]}
        self.client._client.post.return_value = response

        order_id = "order_123"
        self.client.cancel_order(order_id)

        call_args = self.client._client.post.call_args
        body_str = call_args[1]["content"]
        body = json.loads(body_str)

        assert "order_ids" in body
        assert body["order_ids"] == ["order_123"]

    def test_cancel_order_calls_batch_cancel_path(self):
        """cancel_order calls correct API path."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_ids": ["order_123"]}
        self.client._client.post.return_value = response

        self.client.cancel_order("order_123")

        call_args = self.client._client.post.call_args
        url = call_args[0][0]
        assert "/api/v3/brokerage/orders/batch_cancel" in url


class TestGetOrderAndListOrders(unittest.TestCase):
    """Tests for get_order() and list_orders() methods."""

    def setUp(self):
        """Set up test client with mocked HTTP client."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    def test_get_order_calls_correct_path(self):
        """get_order calls correct path with order_id."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"order_id": "order_123", "status": "FILLED"}
        self.client._client.get.return_value = response

        self.client.get_order("order_123")

        call_args = self.client._client.get.call_args
        url = call_args[0][0]
        assert "/api/v3/brokerage/orders/historical/order_123" in url

    def test_list_orders_calls_correct_path(self):
        """list_orders calls correct path."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"orders": []}
        self.client._client.get.return_value = response

        self.client.list_orders()

        call_args = self.client._client.get.call_args
        url = call_args[0][0]
        assert "/api/v3/brokerage/orders/historical/batch" in url

    def test_list_orders_with_product_id_filter(self):
        """list_orders includes product_id parameter."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"orders": []}
        self.client._client.get.return_value = response

        self.client.list_orders(product_id="BTC-USD")

        call_args = self.client._client.get.call_args
        url = call_args[0][0]
        assert "product_id=BTC-USD" in url

    def test_list_orders_with_status_filter(self):
        """list_orders includes status parameter."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"orders": []}
        self.client._client.get.return_value = response

        self.client.list_orders(status="FILLED")

        call_args = self.client._client.get.call_args
        url = call_args[0][0]
        assert "order_status=FILLED" in url


class TestGetAccounts(unittest.TestCase):
    """Tests for get_accounts() method."""

    def setUp(self):
        """Set up test client with mocked HTTP client."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    def test_get_accounts_calls_correct_path(self):
        """get_accounts calls correct path."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"accounts": []}
        self.client._client.get.return_value = response

        self.client.get_accounts()

        call_args = self.client._client.get.call_args
        url = call_args[0][0]
        assert "/api/v3/brokerage/accounts" in url


class TestGetProduct(unittest.TestCase):
    """Tests for get_product() method."""

    def setUp(self):
        """Set up test client with mocked HTTP client."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    def test_get_product_calls_correct_path(self):
        """get_product calls correct path with product_id."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"product_id": "BTC-USD", "base_currency": "BTC"}
        self.client._client.get.return_value = response

        self.client.get_product("BTC-USD")

        call_args = self.client._client.get.call_args
        url = call_args[0][0]
        assert "/api/v3/brokerage/products/BTC-USD" in url


class TestRetryLogic(unittest.TestCase):
    """Tests for retry logic on specific HTTP status codes."""

    def setUp(self):
        """Set up test client with mocked HTTP client and retry policy."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    @patch("quant_core.coinbase_rest.time.sleep")
    def test_retry_on_429_status_code(self, mock_sleep):
        """Retry on 429 status code (rate limited)."""
        # First response: 429, Second response: 200
        responses = [
            Mock(status_code=429, text="Rate limited", headers={}),
            Mock(status_code=200, json=lambda: {"order_id": "12345"}),
        ]
        self.client._client.post.side_effect = responses

        result = self.client.place_order(
            symbol="BTC-USD",
            side="buy",
            size="0.001",
        )

        # Should retry and eventually succeed
        assert result["order_id"] == "12345"
        assert self.client._client.post.call_count == 2
        assert mock_sleep.called

    def test_no_retry_on_400_status_code(self):
        """No retry on 400 status code (client error)."""
        response = Mock(
            status_code=400,
            text="Bad request",
            headers={"content-type": "application/json"},
            json=lambda: {"error": "invalid_symbol"},
        )
        self.client._client.post.return_value = response

        with pytest.raises(CoinbaseAPIError):
            self.client.place_order(
                symbol="INVALID",
                side="buy",
                size="0.001",
            )

        # Should not retry
        assert self.client._client.post.call_count == 1

    def test_no_retry_on_401_status_code(self):
        """No retry on 401 status code (unauthorized)."""
        response = Mock(
            status_code=401,
            text="Unauthorized",
            headers={"content-type": "application/json"},
            json=lambda: {"error": "invalid_auth"},
        )
        self.client._client.post.return_value = response

        with pytest.raises(CoinbaseAPIError):
            self.client.place_order(
                symbol="BTC-USD",
                side="buy",
                size="0.001",
            )

        assert self.client._client.post.call_count == 1

    @patch("quant_core.coinbase_rest.time.sleep")
    def test_retry_on_500_status_code(self, mock_sleep):
        """Retry on 500 status code."""
        responses = [
            Mock(status_code=500, text="Internal Server Error", headers={}),
            Mock(status_code=200, json=lambda: {"success": True}),
        ]
        self.client._client.get.side_effect = responses

        result = self.client.get_accounts()

        assert result["success"] is True
        assert self.client._client.get.call_count == 2

    @patch("quant_core.coinbase_rest.time.sleep")
    def test_retry_on_503_status_code(self, mock_sleep):
        """Retry on 503 Service Unavailable."""
        responses = [
            Mock(status_code=503, text="Service Unavailable", headers={}),
            Mock(status_code=200, json=lambda: {"success": True}),
        ]
        self.client._client.get.side_effect = responses

        result = self.client.get_accounts()

        assert result["success"] is True
        assert self.client._client.get.call_count == 2


class TestCoinbaseAPIError(unittest.TestCase):
    """Tests for CoinbaseAPIError exception."""

    def test_error_has_status_code_attribute(self):
        """CoinbaseAPIError has status_code attribute."""
        error = CoinbaseAPIError(
            status_code=400,
            message="Invalid request",
        )
        assert error.status_code == 400

    def test_error_has_response_attribute(self):
        """CoinbaseAPIError has response attribute."""
        response_data = {"error": "invalid_symbol"}
        error = CoinbaseAPIError(
            status_code=400,
            message="Invalid request",
            response=response_data,
        )
        assert error.response == response_data

    def test_error_response_can_be_none(self):
        """CoinbaseAPIError response attribute can be None."""
        error = CoinbaseAPIError(
            status_code=500,
            message="Server error",
            response=None,
        )
        assert error.response is None

    def test_error_message_format(self):
        """CoinbaseAPIError formats message correctly."""
        error = CoinbaseAPIError(
            status_code=403,
            message="Forbidden",
        )
        assert "403" in str(error)
        assert "Forbidden" in str(error)


class TestRateLimiting(unittest.TestCase):
    """Tests for rate limiting integration."""

    def setUp(self):
        """Set up test client with mocked rate limiter."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    def test_acquire_called_before_request(self):
        """Rate limiter acquire() is called before each request."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"accounts": []}
        self.client._client.get.return_value = response

        self.client.get_accounts()

        # Should call acquire() once
        self.client._limiter.acquire.assert_called()

    def test_acquire_called_multiple_times_on_retry(self):
        """Rate limiter acquire() is called on each retry attempt."""
        responses = [
            Mock(status_code=429, text="Rate limited", headers={}),
            Mock(status_code=200, json=lambda: {"accounts": []}),
        ]
        self.client._client.get.side_effect = responses

        with patch("quant_core.coinbase_rest.time.sleep"):
            self.client.get_accounts()

        # Should call acquire() twice (once per attempt)
        assert self.client._limiter.acquire.call_count == 2


class TestRequestMethods(unittest.TestCase):
    """Tests for HTTP method handling."""

    def setUp(self):
        """Set up test client with mocked HTTP client."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    def test_get_request_uses_get_method(self):
        """_request with GET method calls httpx.Client.get()."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": "test"}
        self.client._client.get.return_value = response

        self.client._request("GET", "/api/v3/test")

        self.client._client.get.assert_called_once()
        self.client._client.post.assert_not_called()
        self.client._client.delete.assert_not_called()

    def test_post_request_uses_post_method(self):
        """_request with POST method calls httpx.Client.post()."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": "test"}
        self.client._client.post.return_value = response

        self.client._request("POST", "/api/v3/test", {"key": "value"})

        self.client._client.post.assert_called_once()
        self.client._client.get.assert_not_called()
        self.client._client.delete.assert_not_called()

    def test_delete_request_uses_delete_method(self):
        """_request with DELETE method calls httpx.Client.delete()."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": "test"}
        self.client._client.delete.return_value = response

        self.client._request("DELETE", "/api/v3/test")

        self.client._client.delete.assert_called_once()
        self.client._client.get.assert_not_called()
        self.client._client.post.assert_not_called()

    def test_unsupported_method_raises_error(self):
        """_request raises ValueError for unsupported HTTP method."""
        with pytest.raises(ValueError, match="Unsupported method"):
            self.client._request("PATCH", "/api/v3/test")


class TestBaseURLHandling(unittest.TestCase):
    """Tests for base URL handling."""

    def test_base_url_strips_trailing_slash(self):
        """Base URL is stored without trailing slash."""
        client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
            base_url="https://api.coinbase.com/",
        )
        assert client._base_url == "https://api.coinbase.com"

    def test_custom_base_url_is_used(self):
        """Custom base_url parameter is respected."""
        custom_url = "https://custom.api.coinbase.com"
        client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
            base_url=custom_url,
        )
        assert client._base_url == custom_url


class TestHTTPErrorHandling(unittest.TestCase):
    """Tests for HTTP error handling."""

    def setUp(self):
        """Set up test client with mocked HTTP client."""
        self.client = CoinbaseRESTClient(
            api_key="test_key",
            api_secret="test_secret",
        )
        self.client._client = MagicMock()
        self.client._limiter = MagicMock()
        self.client._limiter.acquire = MagicMock()

    @patch("quant_core.coinbase_rest.time.sleep")
    def test_http_error_retries(self, mock_sleep):
        """HTTPError triggers retry logic."""
        self.client._client.get.side_effect = [
            httpx.ConnectError("Connection failed"),
            Mock(status_code=200, json=lambda: {"data": "success"}),
        ]

        result = self.client._request("GET", "/api/v3/test")

        assert result["data"] == "success"
        assert self.client._client.get.call_count == 2

    @patch("quant_core.coinbase_rest.time.sleep")
    def test_max_retries_exceeded_raises_error(self, mock_sleep):
        """Exhausting retries raises CoinbaseAPIError."""
        self.client._client.get.side_effect = httpx.ConnectError("Connection failed")

        with pytest.raises(CoinbaseAPIError, match="Max retries exceeded"):
            self.client._request("GET", "/api/v3/test")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
