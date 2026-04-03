"""Per-strategy trading mode manager.

Manages a mapping of strategy_id → trading mode ("paper" or "live").
Supports hot-swapping at runtime via HTTP API without service restart.

Config priority:
  1. Runtime override (via HTTP API) — highest
  2. STRATEGY_MODES env var (e.g., "mean_reversion_btcusd:live,pairs_btcusd_ethusd:paper")
  3. TRADING_MODE env var (global default) — lowest
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

VALID_MODES = {"paper", "live"}


class StrategyModeManager:
    """Thread-safe per-strategy trading mode registry."""

    def __init__(
        self,
        default_mode: str = "paper",
        initial_modes: dict[str, str] | None = None,
    ) -> None:
        self._default = default_mode
        self._modes: dict[str, str] = dict(initial_modes or {})
        self._lock = threading.Lock()

    def get_mode(self, strategy_id: str) -> str:
        """Get the trading mode for a strategy. Falls back to default."""
        with self._lock:
            return self._modes.get(strategy_id, self._default)

    def set_mode(self, strategy_id: str, mode: str) -> None:
        """Set trading mode for a strategy at runtime."""
        if mode not in VALID_MODES:
            msg = f"Invalid mode '{mode}' — must be 'paper' or 'live'"
            raise ValueError(msg)
        with self._lock:
            old = self._modes.get(strategy_id, self._default)
            self._modes[strategy_id] = mode
        logger.info("Strategy mode changed: %s %s → %s", strategy_id, old, mode)

    def remove_override(self, strategy_id: str) -> None:
        """Remove a per-strategy override, reverting to default mode."""
        with self._lock:
            self._modes.pop(strategy_id, None)
        logger.info("Strategy mode override removed: %s (reverted to default '%s')", strategy_id, self._default)

    def get_all(self) -> dict[str, Any]:
        """Return full state for API response."""
        with self._lock:
            return {
                "default_mode": self._default,
                "strategy_overrides": dict(self._modes),
            }

    def has_any_live(self) -> bool:
        """Check if any strategy is in live mode."""
        with self._lock:
            if self._default == "live":
                return True
            return "live" in self._modes.values()


def _make_handler(manager: StrategyModeManager, live_client_ready: bool) -> type:
    """Create an HTTP request handler bound to the given manager."""

    class StrategyModeHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("HTTP %s", format % args)

        def _json_response(self, status: int, body: dict) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self) -> None:
            parsed = urlparse(self.path)

            if parsed.path == "/api/strategy-modes":
                state = manager.get_all()
                state["live_client_ready"] = live_client_ready
                self._json_response(200, state)
            elif parsed.path == "/health":
                self._json_response(200, {"status": "ok", "service": "execution"})
            else:
                self._json_response(404, {"error": "not found"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            if parsed.path == "/api/strategy-modes/set":
                strategy_id = params.get("strategy_id", [None])[0]
                mode = params.get("mode", [None])[0]

                if not strategy_id or not mode:
                    self._json_response(400, {"error": "strategy_id and mode query params required"})
                    return

                if mode not in VALID_MODES:
                    self._json_response(400, {"error": f"mode must be 'paper' or 'live', got '{mode}'"})
                    return

                if mode == "live" and not live_client_ready:
                    self._json_response(400, {"error": "Cannot set live mode — Coinbase client not initialized"})
                    return

                manager.set_mode(strategy_id, mode)
                self._json_response(
                    200,
                    {
                        "strategy_id": strategy_id,
                        "mode": mode,
                        "message": f"Strategy '{strategy_id}' set to '{mode}'",
                    },
                )

            elif parsed.path == "/api/strategy-modes/reset":
                strategy_id = params.get("strategy_id", [None])[0]
                if not strategy_id:
                    self._json_response(400, {"error": "strategy_id query param required"})
                    return
                manager.remove_override(strategy_id)
                self._json_response(
                    200,
                    {
                        "strategy_id": strategy_id,
                        "mode": manager.get_mode(strategy_id),
                        "message": f"Strategy '{strategy_id}' reverted to default",
                    },
                )
            else:
                self._json_response(404, {"error": "not found"})

    return StrategyModeHandler


class _ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def start_mode_api(manager: StrategyModeManager, live_client_ready: bool, port: int = 8091) -> HTTPServer:
    """Start the strategy mode HTTP API in a daemon thread."""
    handler_cls = _make_handler(manager, live_client_ready)
    server = _ReusableHTTPServer(("0.0.0.0", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="strategy-mode-api")
    thread.start()
    logger.info("Strategy mode API listening on port %d", port)
    return server
