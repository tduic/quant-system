"""Tests for market-data exchange WebSocket — Coinbase connection manager."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_data_svc.exchange_ws import (
    ExchangeWebSocket,
    COINBASE_WS_URL,
    to_coinbase_product_id,
    SYMBOL_MAP,
)


class TestSymbolMapping:
    def test_btcusdt_maps_to_btc_usd(self):
        assert to_coinbase_product_id("btcusdt") == "BTC-USD"

    def test_ethusdt_maps_to_eth_usd(self):
        assert to_coinbase_product_id("ethusdt") == "ETH-USD"

    def test_btcusd_maps_to_btc_usd(self):
        assert to_coinbase_product_id("btcusd") == "BTC-USD"

    def test_passthrough_coinbase_format(self):
        assert to_coinbase_product_id("BTC-USD") == "BTC-USD"

    def test_unknown_symbol_raises(self):
        with pytest.raises(ValueError, match="Unknown symbol"):
            to_coinbase_product_id("xyzabc")


class TestExchangeWebSocketURL:
    def test_url_is_coinbase(self):
        ws = ExchangeWebSocket(symbols=["btcusd"], on_message=AsyncMock())
        assert ws.url == COINBASE_WS_URL
        assert "coinbase" in ws.url

    def test_product_ids_mapped(self):
        ws = ExchangeWebSocket(
            symbols=["btcusdt", "ethusdt"],
            on_message=AsyncMock(),
        )
        assert "BTC-USD" in ws.product_ids
        assert "ETH-USD" in ws.product_ids

    def test_symbols_lowercased(self):
        ws = ExchangeWebSocket(symbols=["BTCUSD"], on_message=AsyncMock())
        assert ws._symbols == ["btcusd"]


class TestSubscribeMessage:
    def test_subscribe_contains_product_ids(self):
        ws = ExchangeWebSocket(symbols=["btcusd"], on_message=AsyncMock())
        msg = json.loads(ws._build_subscribe_message())
        assert msg["type"] == "subscribe"
        assert "BTC-USD" in msg["product_ids"]
        assert "matches" in msg["channels"]
        assert "level2_batch" in msg["channels"]


class TestExchangeWebSocketStop:
    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        ws = ExchangeWebSocket(symbols=["btcusd"], on_message=AsyncMock())
        ws._running = True
        ws._ws = None
        await ws.stop()
        assert ws._running is False


class TestExchangeWebSocketConsume:
    @pytest.mark.asyncio
    async def test_consume_dispatches_match(self):
        """_consume should dispatch Coinbase match messages."""
        received = []

        async def capture(msg):
            received.append(msg)

        ws = ExchangeWebSocket(symbols=["btcusd"], on_message=capture)

        raw_messages = [
            json.dumps({
                "type": "match",
                "trade_id": 123,
                "product_id": "BTC-USD",
                "price": "42000.50",
                "size": "0.001",
                "side": "buy",
                "time": "2026-03-21T12:00:00.000000Z",
            }),
            json.dumps({
                "type": "l2update",
                "product_id": "BTC-USD",
                "time": "2026-03-21T12:00:00.100000Z",
                "changes": [["buy", "42000.00", "0.5"]],
            }),
        ]

        mock_ws = AsyncIterator(raw_messages)
        await ws._consume(mock_ws)

        assert len(received) == 2
        assert received[0]["type"] == "match"
        assert received[1]["type"] == "l2update"

    @pytest.mark.asyncio
    async def test_consume_skips_subscriptions(self):
        received = []

        async def capture(msg):
            received.append(msg)

        ws = ExchangeWebSocket(symbols=["btcusd"], on_message=capture)

        raw_messages = [
            json.dumps({"type": "subscriptions", "channels": []}),
            json.dumps({
                "type": "match",
                "trade_id": 456,
                "product_id": "BTC-USD",
                "price": "42000",
                "size": "0.01",
                "side": "sell",
                "time": "2026-03-21T12:00:01.000000Z",
            }),
        ]

        mock_ws = AsyncIterator(raw_messages)
        await ws._consume(mock_ws)

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_consume_handles_invalid_json(self):
        received = []

        async def capture(msg):
            received.append(msg)

        ws = ExchangeWebSocket(symbols=["btcusd"], on_message=capture)

        raw_messages = [
            "not valid json{{{",
            json.dumps({
                "type": "match",
                "trade_id": 789,
                "product_id": "BTC-USD",
                "price": "42000",
                "size": "0.01",
                "side": "buy",
                "time": "2026-03-21T12:00:02.000000Z",
            }),
        ]

        mock_ws = AsyncIterator(raw_messages)
        await ws._consume(mock_ws)

        assert len(received) == 1


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

class AsyncIterator:
    """Mock async iterator to simulate websocket message stream."""

    def __init__(self, items: list[str]):
        self._items = items
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item
