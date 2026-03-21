"""Binance WebSocket connection manager.

Connects to Binance's combined stream endpoint, handles reconnection
with exponential backoff, and dispatches raw messages to a callback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

logger = logging.getLogger(__name__)

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"

# Reconnect backoff parameters
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 60.0
BACKOFF_MULTIPLIER = 2.0

# If no message received in this time, force reconnect
STALE_TIMEOUT_S = 30.0


class BinanceWebSocket:
    """Manages a persistent WebSocket connection to Binance."""

    def __init__(
        self,
        symbols: list[str],
        on_message: Callable[[dict], Awaitable[None]],
    ):
        self._symbols = [s.lower() for s in symbols]
        self._on_message = on_message
        self._running = False
        self._ws = None
        self._message_count = 0

    @property
    def url(self) -> str:
        """Build the combined stream URL for all symbols."""
        streams = []
        for s in self._symbols:
            streams.append(f"{s}@trade")
            streams.append(f"{s}@depth@100ms")
        stream_param = "/".join(streams)
        return f"{BINANCE_WS_BASE}?streams={stream_param}"

    async def start(self) -> None:
        """Connect and start consuming. Reconnects automatically."""
        self._running = True
        backoff = INITIAL_BACKOFF_S

        while self._running:
            try:
                logger.info(
                    "Connecting to Binance WebSocket...",
                    extra={"symbol": ",".join(self._symbols)},
                )
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=10 * 1024 * 1024,  # 10MB max message
                ) as ws:
                    self._ws = ws
                    backoff = INITIAL_BACKOFF_S  # reset on successful connect
                    logger.info("Connected to Binance WebSocket")
                    await self._consume(ws)

            except (ConnectionClosed, ConnectionClosedError) as e:
                logger.warning("WebSocket connection closed: %s", e)
            except (OSError, asyncio.TimeoutError) as e:
                logger.warning("WebSocket connection error: %s", e)
            except Exception:
                logger.exception("Unexpected WebSocket error")

            if self._running:
                logger.info("Reconnecting in %.1fs...", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_S)

    async def stop(self) -> None:
        """Gracefully stop the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _consume(self, ws) -> None:
        """Read messages from the WebSocket and dispatch to callback."""
        async for raw_msg in ws:
            try:
                wrapper = json.loads(raw_msg)
                # Binance combined stream wraps data in {"stream": ..., "data": ...}
                if "data" in wrapper:
                    data = wrapper["data"]
                    data["_stream"] = wrapper.get("stream", "")
                    await self._on_message(data)
                    self._message_count += 1

                    if self._message_count % 10000 == 0:
                        logger.info(
                            "Processed %d messages",
                            self._message_count,
                            extra={"count": self._message_count},
                        )
            except json.JSONDecodeError:
                logger.warning("Failed to parse WebSocket message")
            except Exception:
                logger.exception("Error processing message")
