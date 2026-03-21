"""Exchange WebSocket connection manager.

Connects to Coinbase's WebSocket feed, handles reconnection
with exponential backoff, and dispatches raw messages to a callback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

logger = logging.getLogger(__name__)

COINBASE_WS_URL = os.getenv("EXCHANGE_WS_URL", "wss://ws-feed.exchange.coinbase.com")

# Reconnect backoff parameters
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 60.0
BACKOFF_MULTIPLIER = 2.0

# If no message received in this time, force reconnect
STALE_TIMEOUT_S = 30.0

# Map our internal symbol format to Coinbase product IDs
SYMBOL_MAP = {
    "btcusdt": "BTC-USD",
    "ethusdt": "ETH-USD",
    "btcusd": "BTC-USD",
    "ethusd": "ETH-USD",
}


def to_coinbase_product_id(symbol: str) -> str:
    """Convert internal symbol to Coinbase product ID."""
    s = symbol.lower().strip()
    if s in SYMBOL_MAP:
        return SYMBOL_MAP[s]
    # If already in Coinbase format (e.g., "BTC-USD"), return as-is
    if "-" in symbol:
        return symbol.upper()
    raise ValueError(f"Unknown symbol mapping for: {symbol}")


class ExchangeWebSocket:
    """Manages a persistent WebSocket connection to Coinbase."""

    def __init__(
        self,
        symbols: list[str],
        on_message: Callable[[dict], Awaitable[None]],
    ):
        self._symbols = [s.lower() for s in symbols]
        self._product_ids = [to_coinbase_product_id(s) for s in self._symbols]
        self._on_message = on_message
        self._running = False
        self._ws = None
        self._message_count = 0

    @property
    def url(self) -> str:
        """Return the WebSocket URL."""
        return COINBASE_WS_URL

    @property
    def product_ids(self) -> list[str]:
        return self._product_ids

    def _build_subscribe_message(self) -> str:
        """Build the Coinbase subscribe message."""
        return json.dumps(
            {
                "type": "subscribe",
                "product_ids": self._product_ids,
                "channels": [
                    "matches",  # individual trades
                    "level2_batch",  # order book L2 updates (batched)
                ],
            }
        )

    async def start(self) -> None:
        """Connect and start consuming. Reconnects automatically."""
        self._running = True
        backoff = INITIAL_BACKOFF_S

        while self._running:
            try:
                logger.info(
                    "Connecting to Coinbase WebSocket...",
                    extra={"products": ",".join(self._product_ids)},
                )
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=10 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    backoff = INITIAL_BACKOFF_S

                    # Send subscription message
                    await ws.send(self._build_subscribe_message())
                    logger.info("Subscribed to Coinbase channels")

                    await self._consume(ws)

            except (ConnectionClosed, ConnectionClosedError) as e:
                logger.warning("WebSocket connection closed: %s", e)
            except (TimeoutError, OSError) as e:
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
                data = json.loads(raw_msg)
                msg_type = data.get("type", "")

                # Skip subscription confirmations and heartbeats
                if msg_type in ("subscriptions", "heartbeat"):
                    continue

                if msg_type in ("match", "last_match", "l2update"):
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
