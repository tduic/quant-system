"""Tests for per-strategy trading mode manager and HTTP API."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from unittest.mock import patch

import pytest

from execution_svc.strategy_mode import StrategyModeManager, start_mode_api

# ============================================================================
# StrategyModeManager unit tests
# ============================================================================


class TestStrategyModeManager:
    """Tests for the in-memory strategy mode registry."""

    def test_default_mode_returned_for_unknown_strategy(self):
        """Unknown strategies fall back to the default mode."""
        mgr = StrategyModeManager(default_mode="paper")
        assert mgr.get_mode("unknown_strategy") == "paper"

    def test_default_mode_live(self):
        """Default mode can be set to 'live'."""
        mgr = StrategyModeManager(default_mode="live")
        assert mgr.get_mode("any_strategy") == "live"

    def test_initial_overrides_applied(self):
        """Overrides from STRATEGY_MODES env var are applied at construction."""
        mgr = StrategyModeManager(
            default_mode="paper",
            initial_modes={"mean_reversion_btcusd": "live", "pairs_btcusd_ethusd": "paper"},
        )
        assert mgr.get_mode("mean_reversion_btcusd") == "live"
        assert mgr.get_mode("pairs_btcusd_ethusd") == "paper"
        assert mgr.get_mode("other_strategy") == "paper"

    def test_set_mode_changes_strategy(self):
        """set_mode updates the mode for a specific strategy."""
        mgr = StrategyModeManager(default_mode="paper")
        mgr.set_mode("mean_reversion_btcusd", "live")
        assert mgr.get_mode("mean_reversion_btcusd") == "live"

    def test_set_mode_rejects_invalid(self):
        """set_mode raises ValueError for invalid modes."""
        mgr = StrategyModeManager()
        with pytest.raises(ValueError, match="Invalid mode"):
            mgr.set_mode("strat", "turbo")

    def test_remove_override_reverts_to_default(self):
        """remove_override reverts a strategy to the default mode."""
        mgr = StrategyModeManager(default_mode="paper", initial_modes={"strat_a": "live"})
        assert mgr.get_mode("strat_a") == "live"
        mgr.remove_override("strat_a")
        assert mgr.get_mode("strat_a") == "paper"

    def test_remove_nonexistent_override_is_noop(self):
        """Removing an override that doesn't exist does nothing."""
        mgr = StrategyModeManager(default_mode="paper")
        mgr.remove_override("nonexistent")  # should not raise
        assert mgr.get_mode("nonexistent") == "paper"

    def test_get_all_returns_complete_state(self):
        """get_all returns both default and overrides."""
        mgr = StrategyModeManager(
            default_mode="paper",
            initial_modes={"strat_a": "live"},
        )
        state = mgr.get_all()
        assert state["default_mode"] == "paper"
        assert state["strategy_overrides"] == {"strat_a": "live"}

    def test_has_any_live_with_default_paper(self):
        """has_any_live is False when default is paper and no overrides."""
        mgr = StrategyModeManager(default_mode="paper")
        assert mgr.has_any_live() is False

    def test_has_any_live_with_default_live(self):
        """has_any_live is True when default is live."""
        mgr = StrategyModeManager(default_mode="live")
        assert mgr.has_any_live() is True

    def test_has_any_live_with_override(self):
        """has_any_live is True when any strategy is overridden to live."""
        mgr = StrategyModeManager(default_mode="paper", initial_modes={"strat_a": "live"})
        assert mgr.has_any_live() is True

    def test_thread_safety(self):
        """Concurrent reads and writes don't corrupt state."""
        mgr = StrategyModeManager(default_mode="paper")
        errors = []

        def writer():
            for i in range(100):
                try:
                    mgr.set_mode(f"strat_{i % 5}", "live" if i % 2 == 0 else "paper")
                except Exception as e:
                    errors.append(e)

        def reader():
            for _ in range(100):
                try:
                    mgr.get_mode("strat_0")
                    mgr.get_all()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ============================================================================
# HTTP API tests
# ============================================================================


class TestStrategyModeAPI:
    """Tests for the strategy mode HTTP API."""

    @pytest.fixture(autouse=True)
    def _setup_server(self):
        """Start a mode API server on an OS-assigned port for each test."""
        self.manager = StrategyModeManager(
            default_mode="paper",
            initial_modes={"mean_reversion_btcusd": "live"},
        )
        # Use port 0 so OS assigns a free port each time
        self.server = start_mode_api(self.manager, live_client_ready=True, port=0)
        self.port = self.server.server_address[1]
        yield
        self.server.shutdown()

    def _get(self, path: str) -> tuple[int, dict]:
        conn = HTTPConnection("localhost", self.port, timeout=2)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        return resp.status, body

    def _post(self, path: str) -> tuple[int, dict]:
        conn = HTTPConnection("localhost", self.port, timeout=2)
        conn.request("POST", path)
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        return resp.status, body

    def test_get_strategy_modes(self):
        """GET /api/strategy-modes returns current state."""
        status, body = self._get("/api/strategy-modes")
        assert status == 200
        assert body["default_mode"] == "paper"
        assert body["strategy_overrides"]["mean_reversion_btcusd"] == "live"
        assert body["live_client_ready"] is True

    def test_health_endpoint(self):
        """GET /health returns ok."""
        status, body = self._get("/health")
        assert status == 200
        assert body["status"] == "ok"

    def test_set_mode_via_api(self):
        """POST /api/strategy-modes/set changes a strategy's mode."""
        status, body = self._post("/api/strategy-modes/set?strategy_id=pairs_btcusd_ethusd&mode=live")
        assert status == 200
        assert body["mode"] == "live"
        assert self.manager.get_mode("pairs_btcusd_ethusd") == "live"

    def test_set_mode_missing_params(self):
        """POST /api/strategy-modes/set without params returns 400."""
        status, _body = self._post("/api/strategy-modes/set")
        assert status == 400

    def test_set_invalid_mode(self):
        """POST /api/strategy-modes/set with invalid mode returns 400."""
        status, _body = self._post("/api/strategy-modes/set?strategy_id=strat&mode=turbo")
        assert status == 400

    def test_reset_override(self):
        """POST /api/strategy-modes/reset reverts to default."""
        assert self.manager.get_mode("mean_reversion_btcusd") == "live"
        status, _body = self._post("/api/strategy-modes/reset?strategy_id=mean_reversion_btcusd")
        assert status == 200
        assert self.manager.get_mode("mean_reversion_btcusd") == "paper"

    def test_set_live_rejected_without_client(self):
        """POST to set live mode fails when live_client_ready is False."""
        self.server.shutdown()
        self.server = start_mode_api(self.manager, live_client_ready=False, port=0)
        self.port = self.server.server_address[1]
        status, body = self._post("/api/strategy-modes/set?strategy_id=strat&mode=live")
        assert status == 400
        assert "Coinbase" in body["error"]

    def test_404_on_unknown_path(self):
        """Unknown paths return 404."""
        status, _ = self._get("/api/unknown")
        assert status == 404


# ============================================================================
# Config parsing tests
# ============================================================================


class TestStrategyModesConfig:
    """Tests for STRATEGY_MODES env var parsing."""

    def test_empty_strategy_modes(self):
        """Empty STRATEGY_MODES returns empty dict."""
        with patch.dict("os.environ", {"STRATEGY_MODES": ""}, clear=False):
            from quant_core.config import _parse_strategy_modes

            assert _parse_strategy_modes() == {}

    def test_unset_strategy_modes(self):
        """Unset STRATEGY_MODES returns empty dict."""
        import os

        env = os.environ.copy()
        env.pop("STRATEGY_MODES", None)
        with patch.dict("os.environ", env, clear=True):
            from quant_core.config import _parse_strategy_modes

            assert _parse_strategy_modes() == {}

    def test_single_strategy_mode(self):
        """Single strategy:mode pair is parsed correctly."""
        with patch.dict("os.environ", {"STRATEGY_MODES": "mean_reversion_btcusd:live"}, clear=False):
            from quant_core.config import _parse_strategy_modes

            result = _parse_strategy_modes()
            assert result == {"mean_reversion_btcusd": "live"}

    def test_multiple_strategy_modes(self):
        """Multiple strategy:mode pairs are parsed correctly."""
        with patch.dict("os.environ", {"STRATEGY_MODES": "strat_a:live,strat_b:paper,strat_c:live"}, clear=False):
            from quant_core.config import _parse_strategy_modes

            result = _parse_strategy_modes()
            assert result == {"strat_a": "live", "strat_b": "paper", "strat_c": "live"}

    def test_invalid_mode_raises(self):
        """Invalid mode value raises ValueError."""
        with patch.dict("os.environ", {"STRATEGY_MODES": "strat_a:turbo"}, clear=False):
            from quant_core.config import _parse_strategy_modes

            with pytest.raises(ValueError, match="Invalid strategy mode"):
                _parse_strategy_modes()

    def test_whitespace_handling(self):
        """Whitespace around entries is trimmed."""
        with patch.dict("os.environ", {"STRATEGY_MODES": " strat_a : live , strat_b : paper "}, clear=False):
            from quant_core.config import _parse_strategy_modes

            result = _parse_strategy_modes()
            assert result == {"strat_a": "live", "strat_b": "paper"}


# ============================================================================
# Fill model trading_mode tests
# ============================================================================


class TestFillTradingMode:
    """Tests for the trading_mode field on Fill."""

    def test_fill_default_trading_mode(self):
        """Fill defaults to 'paper' trading_mode."""
        from quant_core.models import Fill

        fill = Fill()
        assert fill.trading_mode == "paper"

    def test_fill_serializes_trading_mode(self):
        """Fill.to_json() includes trading_mode."""
        from quant_core.models import Fill

        fill = Fill(trading_mode="live")
        data = json.loads(fill.to_json())
        assert data["trading_mode"] == "live"

    def test_fill_deserializes_trading_mode(self):
        """Fill.from_json() reads trading_mode."""
        from quant_core.models import Fill

        fill = Fill(trading_mode="live", symbol="BTCUSD", side="BUY")
        restored = Fill.from_json(fill.to_json())
        assert restored.trading_mode == "live"

    def test_fill_backward_compat_no_trading_mode(self):
        """Fill.from_json() defaults to 'paper' for old data without trading_mode."""
        from quant_core.models import Fill

        old_data = json.dumps(
            {
                "fill_id": "abc",
                "timestamp": 123,
                "order_id": "ord-1",
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.1,
                "fill_price": 50000.0,
                "fee": 0.5,
                "slippage_bps": 1.0,
                "backtest_id": None,
                "strategy_id": "strat_a",
            }
        )
        fill = Fill.from_json(old_data)
        assert fill.trading_mode == "paper"
