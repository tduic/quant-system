"""Tests for market-data normalizer — Binance raw → canonical format."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from quant_core.models import Trade, DepthUpdate
from market_data_svc.normalizer import normalize_message


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


class TestNormalizeTrade:
    def test_returns_trade_for_trade_event(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert isinstance(result, Trade)

    def test_trade_has_correct_symbol(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert result.symbol == "BTCUSDT"

    def test_trade_has_correct_price(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert result.price == pytest.approx(43500.25)

    def test_trade_has_correct_quantity(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert result.quantity == pytest.approx(0.05)

    def test_trade_has_correct_trade_id(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert result.trade_id == 99999

    def test_trade_has_buyer_maker_flag(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert result.is_buyer_maker is False

    def test_trade_ingestion_timestamp_is_set(self, binance_trade: dict):
        result = normalize_message(binance_trade)
        assert result.timestamp_ingested > 0


class TestNormalizeDepth:
    def test_returns_depth_update_for_depth_event(self, binance_depth: dict):
        result = normalize_message(binance_depth)
        assert isinstance(result, DepthUpdate)

    def test_depth_has_correct_symbol(self, binance_depth: dict):
        result = normalize_message(binance_depth)
        assert result.symbol == "BTCUSDT"

    def test_depth_has_correct_update_ids(self, binance_depth: dict):
        result = normalize_message(binance_depth)
        assert result.first_update_id == 100
        assert result.final_update_id == 105

    def test_depth_bids_are_float_pairs(self, binance_depth: dict):
        result = normalize_message(binance_depth)
        assert len(result.bids) == 2
        assert result.bids[0][0] == pytest.approx(43500.00)
        assert result.bids[0][1] == pytest.approx(2.0)

    def test_depth_asks_are_float_pairs(self, binance_depth: dict):
        result = normalize_message(binance_depth)
        assert len(result.asks) == 2
        assert result.asks[0][0] == pytest.approx(43501.00)
        assert result.asks[0][1] == pytest.approx(0.5)

    def test_depth_ingestion_timestamp_is_set(self, binance_depth: dict):
        result = normalize_message(binance_depth)
        assert result.timestamp_ingested > 0


class TestNormalizeUnknown:
    def test_returns_none_for_unknown_event(self):
        result = normalize_message({"e": "kline", "s": "BTCUSDT"})
        assert result is None

    def test_returns_none_for_missing_event_type(self):
        result = normalize_message({"s": "BTCUSDT"})
        assert result is None

    def test_returns_none_for_empty_dict(self):
        result = normalize_message({})
        assert result is None
