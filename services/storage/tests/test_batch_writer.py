"""Tests for storage batch_writer — batched bulk inserts to TimescaleDB."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from storage_svc.batch_writer import BatchWriter, PendingTrade, PendingBookSnapshot


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def mock_conn() -> AsyncMock:
    conn = AsyncMock()
    conn.copy_records_to_table = AsyncMock()
    return conn


@pytest.fixture
def mock_pool(mock_conn: AsyncMock) -> AsyncMock:
    pool = MagicMock()
    # pool.acquire() returns an async context manager that yields mock_conn
    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_conn
    ctx.__aexit__.return_value = False
    pool.acquire.return_value = ctx
    return pool


@pytest.fixture
def writer(mock_pool: AsyncMock) -> BatchWriter:
    return BatchWriter(pool=mock_pool, batch_size=5, batch_timeout_ms=1000)


def make_trade(
    symbol: str = "BTCUSDT",
    price: float = 42000.0,
    trade_id: int = 1,
) -> PendingTrade:
    return PendingTrade(
        time=datetime.now(timezone.utc),
        symbol=symbol,
        trade_id=trade_id,
        price=price,
        quantity=0.001,
        is_buyer_maker=False,
        ingestion_latency_us=500,
        backtest_id=None,
    )


def make_book_snapshot(symbol: str = "BTCUSDT") -> PendingBookSnapshot:
    return PendingBookSnapshot(
        time=datetime.now(timezone.utc),
        symbol=symbol,
        bid_prices=[42000.0, 41999.5],
        bid_sizes=[1.0, 2.0],
        ask_prices=[42001.0, 42001.5],
        ask_sizes=[0.5, 1.5],
        spread=1.0,
        mid_price=42000.5,
        backtest_id=None,
    )


# -----------------------------------------------------------------------
# Buffer management
# -----------------------------------------------------------------------

class TestBufferManagement:
    def test_add_trade_increments_buffer(self, writer: BatchWriter):
        assert writer.stats["trade_buffer_size"] == 0
        writer.add_trade(make_trade())
        assert writer.stats["trade_buffer_size"] == 1

    def test_add_book_snapshot_increments_buffer(self, writer: BatchWriter):
        assert writer.stats["book_buffer_size"] == 0
        writer.add_book_snapshot(make_book_snapshot())
        assert writer.stats["book_buffer_size"] == 1

    def test_buffers_are_independent(self, writer: BatchWriter):
        writer.add_trade(make_trade())
        writer.add_book_snapshot(make_book_snapshot())
        assert writer.stats["trade_buffer_size"] == 1
        assert writer.stats["book_buffer_size"] == 1


# -----------------------------------------------------------------------
# should_flush logic
# -----------------------------------------------------------------------

class TestShouldFlush:
    def test_empty_buffer_should_not_flush(self, writer: BatchWriter):
        assert writer.should_flush is False

    def test_full_trade_buffer_should_flush(self, writer: BatchWriter):
        for i in range(5):
            writer.add_trade(make_trade(trade_id=i))
        assert writer.should_flush is True

    def test_partial_buffer_should_not_flush_immediately(self, writer: BatchWriter):
        writer.add_trade(make_trade())
        assert writer.should_flush is False

    def test_full_book_buffer_should_flush(self, writer: BatchWriter):
        for _ in range(5):
            writer.add_book_snapshot(make_book_snapshot())
        assert writer.should_flush is True

    def test_timed_out_buffer_should_flush(self, writer: BatchWriter):
        writer.add_trade(make_trade())
        # Force the last flush time into the past
        writer._last_flush = time.monotonic() - 2.0  # > 1s timeout
        assert writer.should_flush is True

    def test_timed_out_empty_buffer_should_not_flush(self, writer: BatchWriter):
        writer._last_flush = time.monotonic() - 2.0
        assert writer.should_flush is False


# -----------------------------------------------------------------------
# Flush behavior
# -----------------------------------------------------------------------

class TestFlush:
    @pytest.mark.asyncio
    async def test_flush_clears_trade_buffer(self, writer: BatchWriter):
        writer.add_trade(make_trade())
        writer.add_trade(make_trade(trade_id=2))
        assert writer.stats["trade_buffer_size"] == 2

        await writer.flush()
        assert writer.stats["trade_buffer_size"] == 0

    @pytest.mark.asyncio
    async def test_flush_clears_book_buffer(self, writer: BatchWriter):
        writer.add_book_snapshot(make_book_snapshot())
        await writer.flush()
        assert writer.stats["book_buffer_size"] == 0

    @pytest.mark.asyncio
    async def test_flush_increments_total_counts(self, writer: BatchWriter):
        writer.add_trade(make_trade())
        writer.add_trade(make_trade(trade_id=2))
        writer.add_book_snapshot(make_book_snapshot())

        await writer.flush()

        assert writer.stats["total_trades_written"] == 2
        assert writer.stats["total_books_written"] == 1

    @pytest.mark.asyncio
    async def test_flush_accumulates_across_batches(self, writer: BatchWriter):
        writer.add_trade(make_trade())
        await writer.flush()
        writer.add_trade(make_trade(trade_id=2))
        writer.add_trade(make_trade(trade_id=3))
        await writer.flush()

        assert writer.stats["total_trades_written"] == 3

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_is_noop(
        self, writer: BatchWriter, mock_pool: AsyncMock
    ):
        await writer.flush()
        # Pool should not be accessed if nothing to flush
        mock_pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_calls_copy_records_for_trades(
        self, writer: BatchWriter, mock_conn: AsyncMock
    ):
        writer.add_trade(make_trade())
        await writer.flush()

        mock_conn.copy_records_to_table.assert_called()
        call_kwargs = mock_conn.copy_records_to_table.call_args
        assert call_kwargs.kwargs["columns"][0] == "time"

    @pytest.mark.asyncio
    async def test_flush_resets_last_flush_time(self, writer: BatchWriter):
        old_time = writer._last_flush
        writer.add_trade(make_trade())
        await writer.flush()
        assert writer._last_flush >= old_time


# -----------------------------------------------------------------------
# PendingTrade / PendingBookSnapshot data integrity
# -----------------------------------------------------------------------

class TestPendingModels:
    def test_pending_trade_fields(self):
        now = datetime.now(timezone.utc)
        trade = PendingTrade(
            time=now,
            symbol="ETHUSDT",
            trade_id=42,
            price=3000.0,
            quantity=1.5,
            is_buyer_maker=True,
            ingestion_latency_us=200,
            backtest_id="bt-test",
        )
        assert trade.symbol == "ETHUSDT"
        assert trade.price == 3000.0
        assert trade.backtest_id == "bt-test"

    def test_pending_book_snapshot_fields(self):
        snap = make_book_snapshot("SOLUSDT")
        assert snap.symbol == "SOLUSDT"
        assert len(snap.bid_prices) == 2
        assert len(snap.ask_sizes) == 2
        assert snap.spread == pytest.approx(1.0)
        assert snap.mid_price == pytest.approx(42000.5)

    def test_pending_trade_with_none_backtest(self):
        trade = make_trade()
        assert trade.backtest_id is None
