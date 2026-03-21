"""Normalize raw exchange messages into internal canonical format.

Each exchange adapter has its own parsing logic. This module dispatches
based on message format and converts to our Trade and DepthUpdate dataclasses.
"""

from __future__ import annotations

import logging

from quant_core.models import Trade, DepthUpdate, now_ms

logger = logging.getLogger(__name__)


def normalize_message(raw: dict) -> Trade | DepthUpdate | None:
    """Normalize a raw WebSocket message from any supported exchange.

    Currently supports:
    - Coinbase: "match" / "last_match" -> Trade, "l2update" -> DepthUpdate
    - Binance: "trade" -> Trade, "depthUpdate" -> DepthUpdate

    Returns a Trade or DepthUpdate, or None if the message type is unrecognized.
    """
    ingested_at = now_ms()

    # Coinbase messages use "type" field
    msg_type = raw.get("type", "")

    if msg_type in ("match", "last_match"):
        return Trade.from_coinbase(raw, ingested_at)

    elif msg_type == "l2update":
        return DepthUpdate.from_coinbase(raw, ingested_at)

    # Binance messages use "e" field
    event_type = raw.get("e", "")

    if event_type == "trade":
        return Trade.from_binance(raw, ingested_at)

    elif event_type == "depthUpdate":
        return DepthUpdate.from_binance(raw, ingested_at)

    logger.debug("Skipping unknown message type: %s / %s", msg_type, event_type)
    return None
