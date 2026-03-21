"""Batched writer for TimescaleDB.

Accumulates rows in memory and flushes them to the database in batches
using PostgreSQL's COPY protocol for maximum throughput.
Flushes when batch_size is reached OR batch_timeout expires, whichever
comes first.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class PendingTrade:
    time: datetime
    symbol: str
    trade_id: int
    price: float
    quantity: float
    is_buyer_maker: bool
    ingestion_latency_us: int | None
    backtest_id: str | None


@dataclass
class PendingBookSnapshot:
    time: datetime
    symbol: str
    bid_prices: list[float]
    bid_sizes: list[float]
    ask_prices: list[float]
    ask_sizes: list[float]
    spread: float
    mid_price: float
    backtest_id: str | None


class BatchWriter:
    """Accumulates rows and bulk-inserts them into TimescaleDB."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        batch_size: int = 1000,
        batch_timeout_ms: int = 1000,
    ):
        self._pool = pool
        self._batch_size = batch_size
        self._batch_timeout_s = batch_timeout_ms / 1000.0

        self._trade_buffer: list[PendingTrade] = []
        self._book_buffer: list[PendingBookSnapshot] = []
        self._last_flush = time.monotonic()

        self._total_trades_written = 0
        self._total_books_written = 0

    def add_trade(self, trade: PendingTrade) -> None:
        """Add a trade to the buffer."""
        self._trade_buffer.append(trade)

    def add_book_snapshot(self, snap: PendingBookSnapshot) -> None:
        """Add an order book snapshot to the buffer."""
        self._book_buffer.append(snap)

    @property
    def should_flush(self) -> bool:
        """Check if we should flush based on buffer size or timeout."""
        buffer_full = (
            len(self._trade_buffer) >= self._batch_size
            or len(self._book_buffer) >= self._batch_size
        )
        timed_out = (
            time.monotonic() - self._last_flush >= self._batch_timeout_s
            and bool(self._trade_buffer or self._book_buffer)
        )
        return buffer_full or timed_out

    async def flush(self) -> None:
        """Write all buffered rows to the database."""
        trades = self._trade_buffer
        books = self._book_buffer
        self._trade_buffer = []
        self._book_buffer = []
        self._last_flush = time.monotonic()

        if not trades and not books:
            return

        async with self._pool.acquire() as conn:
            if trades:
                await self._write_trades(conn, trades)
                self._total_trades_written += len(trades)

            if books:
                await self._write_books(conn, books)
                self._total_books_written += len(books)

        if trades or books:
            logger.info(
                "Flushed %d trades, %d book snapshots (total: %d / %d)",
                len(trades),
                len(books),
                self._total_trades_written,
                self._total_books_written,
                extra={
                    "count": len(trades) + len(books),
                },
            )

    async def _write_trades(
        self, conn: asyncpg.Connection, trades: list[PendingTrade]
    ) -> None:
        """Bulk insert trades using copy_records_to_table."""
        records = [
            (
                t.time,
                t.symbol,
                t.trade_id,
                t.price,
                t.quantity,
                t.is_buyer_maker,
                t.ingestion_latency_us,
                t.backtest_id,
            )
            for t in trades
        ]
        try:
            await conn.copy_records_to_table(
                "trades",
                records=records,
                columns=[
                    "time",
                    "symbol",
                    "trade_id",
                    "price",
                    "quantity",
                    "is_buyer_maker",
                    "ingestion_latency_us",
                    "backtest_id",
                ],
            )
        except Exception:
            logger.exception("Failed to write %d trades", len(trades))
            raise

    async def _write_books(
        self, conn: asyncpg.Connection, books: list[PendingBookSnapshot]
    ) -> None:
        """Bulk insert order book snapshots."""
        records = [
            (
                b.time,
                b.symbol,
                b.bid_prices,
                b.bid_sizes,
                b.ask_prices,
                b.ask_sizes,
                b.spread,
                b.mid_price,
                b.backtest_id,
            )
            for b in books
        ]
        try:
            await conn.copy_records_to_table(
                "order_book_snapshots",
                records=records,
                columns=[
                    "time",
                    "symbol",
                    "bid_prices",
                    "bid_sizes",
                    "ask_prices",
                    "ask_sizes",
                    "spread",
                    "mid_price",
                    "backtest_id",
                ],
            )
        except Exception:
            logger.exception("Failed to write %d book snapshots", len(books))
            raise

    @property
    def stats(self) -> dict[str, int]:
        return {
            "total_trades_written": self._total_trades_written,
            "total_books_written": self._total_books_written,
            "trade_buffer_size": len(self._trade_buffer),
            "book_buffer_size": len(self._book_buffer),
        }
