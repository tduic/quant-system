"""Normalize raw Binance messages into internal canonical format.

Each exchange adapter has its own normalizer. This one handles Binance's
trade and depth stream formats and converts them to our Trade and DepthUpdate
dataclasses.
"""

from __future__ import annotations

import logging

from quant_core.models import Trade, DepthUpdate, now_ms

logger = logging.getLogger(__name__)


def normalize_message(raw: dict) -> Trade | DepthUpdate | None:
    """Normalize a raw Binance WebSocket message.

    Returns a Trade or DepthUpdate, or None if the message type is unrecognized.
    """
    ingested_at = now_ms()
    event_type = raw.get("e", "")

    if event_type == "trade":
        return Trade.from_binance(raw, ingested_at)

    elif event_type == "depthUpdate":
        return DepthUpdate.from_binance(raw, ingested_at)

    else:
        # Unknown event type — log and skip
        logger.debug("Skipping unknown event type: %s", event_type)
        return None
