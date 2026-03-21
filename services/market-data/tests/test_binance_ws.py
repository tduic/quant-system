"""Tests for market-data binance_ws — WebSocket connection manager."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_data_svc.binance_ws import BinanceWebSocket, BINANCE_WS_BASE


class TestBinanceWebSocketURL:
    def test_single_symbol_url(self):
        ws = BinanceWebSocket(symbols=["btcusdt"], on_message=AsyncMock())
        assert "btcusdt@trade" in ws.url
        assert "btcusdt@depth@100ms" in ws.url
        assert ws.url.startswith(BINANCE_WS_BASE)

    def test_multiple_symbols_url(self):
        ws = BinanceWebSocket(
            symbols=["btcusdt", "ethusdt"],
            on_message=AsyncMock(),
        )
        url = ws.url
        assert "btcusdt@trade" in url
        assert "btcusdt@depth@100ms" in url
        assert "ethusdt@trade" in url
        assert "ethusdt@depth@100ms" in url
        # Streams joined by /
        assert "/" in url.split("?streams=")[1]

    def test_symbols_lowercased(self):
        ws = BinanceWebSocket(symbols=["BTCUSDT"], on_message=AsyncMock())
        assert "btcusdt@trade" in ws.url

    def test_url_format(self):
        ws = BinanceWebSocket(symbols=["btcusdt"], on_message=AsyncMock())
        assert ws.url.startswith("wss://stream.binance.com")
        assert "?streams=" in ws.url


class TestBinanceWebSocketStop:
    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        ws = BinanceWebSocket(symbols=["btcusdt"], on_message=AsyncMock())
        ws._running = True
        ws._ws = None
        await ws.stop()
        assert ws._running is False


class TestBinanceWebSocketConsume:
    @pytest.mark.asyncio
    async def test_consume_dispatches_data_field(self):
        """_consume should extract the 'data' field and call on_message."""
        received = []

        async def capture(msg):
            received.append(msg)

        ws = BinanceWebSocket(symbols=["btcusdt"], on_message=capture)

        # Simulate websocket messages
        raw_messages = [
            json.dumps({
                "stream": "btcusdt@trade",
                "data": {"e": "trade", "s": "BTCUSDT", "p": "42000", "q": "0.1"},
            }),
            json.dumps({
                "stream": "btcusdt@depth@100ms",
                "data": {"e": "depthUpdate", "s": "BTCUSDT", "b": [], "a": []},
            }),
        ]

        # Mock a websocket that yields our messages then stops
        mock_ws = AsyncIterator(raw_messages)
        await ws._consume(mock_ws)

        assert len(received) == 2
        assert received[0]["e"] == "trade"
        assert received[0]["_stream"] == "btcusdt@trade"
        assert received[1]["e"] == "depthUpdate"

    @pytest.mark.asyncio
    async def test_consume_skips_messages_without_data(self):
        received = []

        async def capture(msg):
            received.append(msg)

        ws = BinanceWebSocket(symbols=["btcusdt"], on_message=capture)

        raw_messages = [
            json.dumps({"result": None, "id": 1}),  # subscription response
            json.dumps({
                "stream": "btcusdt@trade",
                "data": {"e": "trade", "s": "BTCUSDT"},
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

        ws = BinanceWebSocket(symbols=["btcusdt"], on_message=capture)

        raw_messages = [
            "not valid json{{{",
            json.dumps({
                "stream": "btcusdt@trade",
                "data": {"e": "trade", "s": "BTCUSDT"},
            }),
        ]

        mock_ws = AsyncIterator(raw_messages)
        await ws._consume(mock_ws)

        # Should skip the bad message and process the good one
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
