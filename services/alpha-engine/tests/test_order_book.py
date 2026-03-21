"""Tests for alpha_engine_svc.order_book — L2 order book."""

from __future__ import annotations

import pytest

from quant_core.models import DepthUpdate
from alpha_engine_svc.order_book import OrderBook


@pytest.fixture
def book() -> OrderBook:
    return OrderBook(symbol="BTCUSD")


@pytest.fixture
def populated_book(book: OrderBook) -> OrderBook:
    """Book with 3 bid levels and 3 ask levels."""
    book.apply_delta(DepthUpdate(
        symbol="BTCUSD",
        bids=[[100.0, 1.0], [99.0, 2.0], [98.0, 3.0]],
        asks=[[101.0, 1.5], [102.0, 2.5], [103.0, 0.5]],
    ))
    return book


class TestApplyDelta:
    def test_adds_new_levels(self, book: OrderBook):
        book.apply_delta(DepthUpdate(
            bids=[[100.0, 1.0]],
            asks=[[101.0, 2.0]],
        ))
        assert book.best_bid() == (100.0, 1.0)
        assert book.best_ask() == (101.0, 2.0)

    def test_updates_existing_levels(self, populated_book: OrderBook):
        populated_book.apply_delta(DepthUpdate(
            bids=[[100.0, 5.0]],
            asks=[],
        ))
        assert populated_book.best_bid() == (100.0, 5.0)

    def test_removes_levels_with_zero_quantity(self, populated_book: OrderBook):
        populated_book.apply_delta(DepthUpdate(
            bids=[[100.0, 0.0]],
            asks=[],
        ))
        # Best bid should now be 99.0
        assert populated_book.best_bid() == (99.0, 2.0)

    def test_remove_nonexistent_level_is_noop(self, book: OrderBook):
        book.apply_delta(DepthUpdate(bids=[[50.0, 0.0]], asks=[]))
        assert book.best_bid() is None


class TestBestBidAsk:
    def test_best_bid_is_highest_price(self, populated_book: OrderBook):
        assert populated_book.best_bid()[0] == 100.0

    def test_best_ask_is_lowest_price(self, populated_book: OrderBook):
        assert populated_book.best_ask()[0] == 101.0

    def test_empty_book_returns_none(self, book: OrderBook):
        assert book.best_bid() is None
        assert book.best_ask() is None


class TestMidPrice:
    def test_mid_price(self, populated_book: OrderBook):
        assert populated_book.mid_price() == pytest.approx(100.5)

    def test_mid_price_empty_book(self, book: OrderBook):
        assert book.mid_price() is None

    def test_mid_price_no_asks(self, book: OrderBook):
        book.apply_delta(DepthUpdate(bids=[[100.0, 1.0]], asks=[]))
        assert book.mid_price() is None


class TestSpread:
    def test_spread(self, populated_book: OrderBook):
        assert populated_book.spread() == pytest.approx(1.0)

    def test_spread_empty_book(self, book: OrderBook):
        assert book.spread() is None


class TestImbalance:
    def test_balanced_book(self, book: OrderBook):
        book.apply_delta(DepthUpdate(
            bids=[[100.0, 1.0]],
            asks=[[101.0, 1.0]],
        ))
        assert book.imbalance(levels=1) == pytest.approx(0.0)

    def test_bid_heavy_book(self, book: OrderBook):
        book.apply_delta(DepthUpdate(
            bids=[[100.0, 10.0]],
            asks=[[101.0, 1.0]],
        ))
        imb = book.imbalance(levels=1)
        assert imb > 0.0
        assert imb == pytest.approx((10.0 - 1.0) / 11.0)

    def test_ask_heavy_book(self, book: OrderBook):
        book.apply_delta(DepthUpdate(
            bids=[[100.0, 1.0]],
            asks=[[101.0, 10.0]],
        ))
        assert book.imbalance(levels=1) < 0.0

    def test_empty_book_imbalance(self, book: OrderBook):
        assert book.imbalance() == 0.0

    def test_imbalance_respects_levels(self, populated_book: OrderBook):
        # With 1 level: bid=1.0, ask=1.5
        imb1 = populated_book.imbalance(levels=1)
        # With all 3 levels: bid=6.0, ask=4.5
        imb3 = populated_book.imbalance(levels=3)
        assert imb1 != imb3


class TestTopLevels:
    def test_top_bids_sorted_descending(self, populated_book: OrderBook):
        bids = populated_book.top_bids(3)
        assert len(bids) == 3
        assert bids[0][0] > bids[1][0] > bids[2][0]

    def test_top_asks_sorted_ascending(self, populated_book: OrderBook):
        asks = populated_book.top_asks(3)
        assert len(asks) == 3
        assert asks[0][0] < asks[1][0] < asks[2][0]

    def test_top_bids_limits_count(self, populated_book: OrderBook):
        assert len(populated_book.top_bids(2)) == 2

    def test_top_asks_limits_count(self, populated_book: OrderBook):
        assert len(populated_book.top_asks(1)) == 1
