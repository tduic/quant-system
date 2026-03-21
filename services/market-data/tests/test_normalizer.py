"""Tests for market-data normalizer — raw exchange messages → canonical format."""

from __future__ import annotations

import pytest

from market_data_svc.normalizer import normalize_message
from quant_core.models import DepthUpdate, Trade

# -----------------------------------------------------------------------
# Coinbase fixtures
# -----------------------------------------------------------------------


@pytest.fixture
def coinbase_match() -> dict:
    return {
        "type": "match",
        "trade_id": 123456,
        "product_id": "BTC-USD",
        "price": "43500.25",
        "size": "0.05",
        "side": "buy",
        "time": "2026-03-21T12:00:00.000000Z",
    }


@pytest.fixture
def coinbase_l2update() -> dict:
    return {
        "type": "l2update",
        "product_id": "BTC-USD",
        "time": "2026-03-21T12:00:00.100000Z",
        "changes": [
            ["buy", "43500.00", "2.0"],
            ["buy", "43499.50", "1.5"],
            ["sell", "43501.00", "0.5"],
            ["sell", "43501.50", "3.0"],
        ],
    }


# -----------------------------------------------------------------------
# Binance fixtures (kept for backward compat)
# -----------------------------------------------------------------------


@pytest.fixture
def binance_trade() -> dict:
    return {
        "e": "trade",
        "E": 1672515782136,
        "s": "BTCUSDT",
        "t": 99999,
        "p": "43500.25",
        "q": "0.05",
        "b": 88,
        "a": 50,
        "T": 1672515782100,
        "m": False,
        "M": True,
    }


@pytest.fixture
def binance_depth() -> dict:
    return {
        "e": "depthUpdate",
        "E": 1672515782136,
        "s": "BTCUSDT",
        "U": 100,
        "u": 105,
        "b": [["43500.00", "2.0"], ["43499.50", "1.5"]],
        "a": [["43501.00", "0.5"], ["43501.50", "3.0"]],
    }


# -----------------------------------------------------------------------
# Coinbase trade tests
# -----------------------------------------------------------------------


class TestNormalizeCoinbaseTrade:
    def test_returns_trade_for_match(self, coinbase_match: dict):
        result = normalize_message(coinbase_match)
        assert isinstance(result, Trade)

    def test_trade_has_correct_symbol(self, coinbase_match: dict):
        result = normalize_message(coinbase_match)
        assert result.symbol == "BTCUSD"

    def test_trade_has_correct_price(self, coinbase_match: dict):
        result = normalize_message(coinbase_match)
        assert result.price == pytest.approx(43500.25)

    def test_trade_has_correct_quantity(self, coinbase_match: dict):
        result = normalize_message(coinbase_match)
        assert result.quantity == pytest.approx(0.05)

    def test_trade_has_correct_trade_id(self, coinbase_match: dict):
        result = normalize_message(coinbase_match)
        assert result.trade_id == 123456

    def test_trade_buyer_maker_for_buy_taker(self, coinbase_match: dict):
        # Taker side is "buy", so maker was seller → is_buyer_maker = False
        result = normalize_message(coinbase_match)
        assert result.is_buyer_maker is False

    def test_trade_buyer_maker_for_sell_taker(self, coinbase_match: dict):
        coinbase_match["side"] = "sell"
        result = normalize_message(coinbase_match)
        assert result.is_buyer_maker is True

    def test_trade_exchange_is_coinbase(self, coinbase_match: dict):
        result = normalize_message(coinbase_match)
        assert result.exchange == "coinbase"

    def test_trade_ingestion_timestamp_is_set(self, coinbase_match: dict):
        result = normalize_message(coinbase_match)
        assert result.timestamp_ingested > 0

    def test_last_match_also_returns_trade(self, coinbase_match: dict):
        coinbase_match["type"] = "last_match"
        result = normalize_message(coinbase_match)
        assert isinstance(result, Trade)


# -----------------------------------------------------------------------
# Coinbase depth tests
# -----------------------------------------------------------------------


class TestNormalizeCoinbaseDepth:
    def test_returns_depth_update_for_l2update(self, coinbase_l2update: dict):
        result = normalize_message(coinbase_l2update)
        assert isinstance(result, DepthUpdate)

    def test_depth_has_correct_symbol(self, coinbase_l2update: dict):
        result = normalize_message(coinbase_l2update)
        assert result.symbol == "BTCUSD"

    def test_depth_bids_parsed(self, coinbase_l2update: dict):
        result = normalize_message(coinbase_l2update)
        assert len(result.bids) == 2
        assert result.bids[0][0] == pytest.approx(43500.00)
        assert result.bids[0][1] == pytest.approx(2.0)

    def test_depth_asks_parsed(self, coinbase_l2update: dict):
        result = normalize_message(coinbase_l2update)
        assert len(result.asks) == 2
        assert result.asks[0][0] == pytest.approx(43501.00)
        assert result.asks[0][1] == pytest.approx(0.5)

    def test_depth_exchange_is_coinbase(self, coinbase_l2update: dict):
        result = normalize_message(coinbase_l2update)
        assert result.exchange == "coinbase"

    def test_depth_ingestion_timestamp_is_set(self, coinbase_l2update: dict):
        result = normalize_message(coinbase_l2update)
        assert result.timestamp_ingested > 0


# -----------------------------------------------------------------------
# Binance backward compat tests
# -----------------------------------------------------------------------


class TestNormalizeBinanceTrade:
    def test_returns_trade_for_trade_event(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert isinstance(result, Trade)

    def test_trade_has_correct_symbol(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert result.symbol == "BTCUSDT"

    def test_trade_has_correct_price(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert result.price == pytest.approx(43500.25)


class TestNormalizeBinanceDepth:
    def test_returns_depth_update(self, binance_depth: dict):
        result = normalize_message(binance_depth)
        assert isinstance(result, DepthUpdate)

    def test_depth_has_correct_symbol(self, binance_depth: dict):
        result = normalize_message(binance_depth)
        assert result.symbol == "BTCUSDT"


# -----------------------------------------------------------------------
# Unknown / edge cases
# -----------------------------------------------------------------------


class TestNormalizeUnknown:
    def test_returns_none_for_unknown_event(self):
        result = normalize_message({"e": "kline", "s": "BTCUSDT"})
        assert result is None

    def test_returns_none_for_unknown_type(self):
        result = normalize_message({"type": "ticker", "product_id": "BTC-USD"})
        assert result is None

    def test_returns_none_for_missing_event_type(self):
        result = normalize_message({"s": "BTCUSDT"})
        assert result is None

    def test_returns_none_for_empty_dict(self):
        result = normalize_message({})
        assert result is None
