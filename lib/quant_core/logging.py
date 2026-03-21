"""Structured JSON logging for all services.

Usage:
    from quant_core.logging import setup_logging
    setup_logging("market-data", level="INFO")
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Include extra fields
        for key in ("symbol", "topic", "backtest_id", "latency_ms", "count"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        return json.dumps(log_entry)


def setup_logging(service_name: str, level: str = "INFO") -> None:
    """Configure root logger with JSON output to stdout."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(service_name))
    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("confluent_kafka").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
