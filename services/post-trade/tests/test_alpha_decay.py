"""Tests for alpha decay tracking and IC computation."""

from __future__ import annotations

import pytest

from post_trade_svc.alpha_decay import AlphaDecayTracker


class TestAlphaDecayTracker:
    """Test signal recording, horizon evaluation, and IC computation."""

    def _make_tracker(self, horizons_ms=None, max_signals=100):
        horizons = horizons_ms or [60_000, 300_000]  # 1m, 5m for tests
        return AlphaDecayTracker(horizons_ms=horizons, max_signals=max_signals)

    # --- Signal Recording ---

    def test_record_signal_stores_entry(self):
        tracker = self._make_tracker()
        tracker.record_signal(
            signal_id="s1",
            timestamp_ms=1000,
            strategy_id="mean_reversion_BTCUSD",
            symbol="BTCUSD",
            side="BUY",
            strength=0.8,
            mid_price=50_000.0,
        )
        assert len(tracker._signals) == 1
        assert tracker._signals[0].signal_id == "s1"
        assert tracker._signals[0].predicted_direction == 0.8  # BUY * strength

    def test_sell_signal_has_negative_direction(self):
        tracker = self._make_tracker()
        tracker.record_signal(
            signal_id="s2",
            timestamp_ms=2000,
            strategy_id="mean_reversion_BTCUSD",
            symbol="BTCUSD",
            side="SELL",
            strength=0.6,
            mid_price=50_000.0,
        )
        assert tracker._signals[0].predicted_direction == pytest.approx(-0.6)

    def test_max_signals_eviction(self):
        tracker = self._make_tracker(max_signals=3)
        for i in range(5):
            tracker.record_signal(
                signal_id=f"s{i}",
                timestamp_ms=i * 1000,
                strategy_id="strat",
                symbol="BTCUSD",
                side="BUY",
                strength=1.0,
                mid_price=50_000.0,
            )
        assert len(tracker._signals) == 3
        assert tracker._signals[0].signal_id == "s2"  # oldest remaining

    # --- Horizon Return Evaluation ---

    def test_on_trade_fills_horizon_returns(self):
        tracker = self._make_tracker(horizons_ms=[60_000])
        tracker.record_signal(
            signal_id="s1",
            timestamp_ms=0,
            strategy_id="strat",
            symbol="BTCUSD",
            side="BUY",
            strength=1.0,
            mid_price=50_000.0,
        )
        # Trade at 61s — should fill the 60s horizon
        tracker.on_trade(symbol="BTCUSD", timestamp_ms=61_000, price=50_500.0)
        sig = tracker._signals[0]
        assert sig.horizon_returns[60_000] == pytest.approx(0.01)  # +1%

    def test_on_trade_does_not_fill_before_horizon(self):
        tracker = self._make_tracker(horizons_ms=[60_000])
        tracker.record_signal(
            signal_id="s1",
            timestamp_ms=0,
            strategy_id="strat",
            symbol="BTCUSD",
            side="BUY",
            strength=1.0,
            mid_price=50_000.0,
        )
        tracker.on_trade(symbol="BTCUSD", timestamp_ms=30_000, price=50_500.0)
        sig = tracker._signals[0]
        assert sig.horizon_returns[60_000] is None

    def test_on_trade_ignores_wrong_symbol(self):
        tracker = self._make_tracker(horizons_ms=[60_000])
        tracker.record_signal(
            signal_id="s1",
            timestamp_ms=0,
            strategy_id="strat",
            symbol="BTCUSD",
            side="BUY",
            strength=1.0,
            mid_price=50_000.0,
        )
        tracker.on_trade(symbol="ETHUSD", timestamp_ms=61_000, price=3_000.0)
        sig = tracker._signals[0]
        assert sig.horizon_returns[60_000] is None

    def test_on_trade_uses_first_price_after_horizon(self):
        """Once a horizon is filled, later trades should not overwrite it."""
        tracker = self._make_tracker(horizons_ms=[60_000])
        tracker.record_signal(
            signal_id="s1",
            timestamp_ms=0,
            strategy_id="strat",
            symbol="BTCUSD",
            side="BUY",
            strength=1.0,
            mid_price=50_000.0,
        )
        tracker.on_trade(symbol="BTCUSD", timestamp_ms=61_000, price=50_500.0)
        tracker.on_trade(symbol="BTCUSD", timestamp_ms=120_000, price=51_000.0)
        sig = tracker._signals[0]
        assert sig.horizon_returns[60_000] == pytest.approx(0.01)  # first fill wins

    def test_multiple_horizons_filled_independently(self):
        tracker = self._make_tracker(horizons_ms=[60_000, 300_000])
        tracker.record_signal(
            signal_id="s1",
            timestamp_ms=0,
            strategy_id="strat",
            symbol="BTCUSD",
            side="BUY",
            strength=1.0,
            mid_price=50_000.0,
        )
        # Fill 1m horizon
        tracker.on_trade(symbol="BTCUSD", timestamp_ms=61_000, price=50_500.0)
        sig = tracker._signals[0]
        assert sig.horizon_returns[60_000] == pytest.approx(0.01)
        assert sig.horizon_returns[300_000] is None

        # Fill 5m horizon
        tracker.on_trade(symbol="BTCUSD", timestamp_ms=301_000, price=51_000.0)
        assert sig.horizon_returns[300_000] == pytest.approx(0.02)

    # --- IC Computation ---

    def test_compute_ic_perfect_positive_correlation(self):
        """Stronger BUY signals → bigger price increases → IC ≈ 1.0."""
        tracker = self._make_tracker(horizons_ms=[60_000])
        for i in range(10):
            strength = 0.1 * (i + 1)  # varying strength 0.1..1.0
            tracker.record_signal(
                signal_id=f"s{i}",
                timestamp_ms=i * 1_000_000,
                strategy_id="strat",
                symbol="BTCUSD",
                side="BUY",
                strength=strength,
                mid_price=50_000.0,
            )
            # Price increase proportional to strength
            tracker.on_trade(
                symbol="BTCUSD",
                timestamp_ms=i * 1_000_000 + 61_000,
                price=50_000.0 + strength * 1000,
            )

        result = tracker.get_alpha_decay_data()
        ic_1m = result["horizons"][0]
        assert ic_1m["horizon_label"] == "1m"
        assert ic_1m["ic"] == pytest.approx(1.0, abs=0.01)

    def test_compute_ic_perfect_negative_correlation(self):
        """Stronger BUY signals → bigger price decreases → IC ≈ -1.0."""
        tracker = self._make_tracker(horizons_ms=[60_000])
        for i in range(10):
            strength = 0.1 * (i + 1)  # varying strength
            tracker.record_signal(
                signal_id=f"s{i}",
                timestamp_ms=i * 1_000_000,
                strategy_id="strat",
                symbol="BTCUSD",
                side="BUY",
                strength=strength,
                mid_price=50_000.0,
            )
            # Price decrease proportional to strength (inversely correlated)
            tracker.on_trade(
                symbol="BTCUSD",
                timestamp_ms=i * 1_000_000 + 61_000,
                price=50_000.0 - strength * 1000,
            )

        result = tracker.get_alpha_decay_data()
        ic_1m = result["horizons"][0]
        assert ic_1m["ic"] == pytest.approx(-1.0, abs=0.01)

    def test_compute_ic_insufficient_data(self):
        """IC should be None with fewer than 5 completed signals."""
        tracker = self._make_tracker(horizons_ms=[60_000])
        for i in range(3):
            tracker.record_signal(
                signal_id=f"s{i}",
                timestamp_ms=i * 1_000_000,
                strategy_id="strat",
                symbol="BTCUSD",
                side="BUY",
                strength=1.0,
                mid_price=50_000.0,
            )
            tracker.on_trade(
                symbol="BTCUSD",
                timestamp_ms=i * 1_000_000 + 61_000,
                price=50_500.0,
            )

        result = tracker.get_alpha_decay_data()
        assert result["horizons"][0]["ic"] is None

    def test_ic_decays_over_longer_horizons(self):
        """IC at shorter horizons should be >= IC at longer horizons for a decaying signal."""
        tracker = self._make_tracker(horizons_ms=[60_000, 300_000])

        # Signals predict short-term direction well, but it fades
        for i in range(20):
            side = "BUY" if i % 2 == 0 else "SELL"
            strength = 0.5 + 0.025 * i  # varying strength for valid correlation
            mid = 50_000.0
            direction = 1 if side == "BUY" else -1

            tracker.record_signal(
                signal_id=f"s{i}",
                timestamp_ms=i * 1_000_000,
                strategy_id="strat",
                symbol="BTCUSD",
                side=side,
                strength=strength,
                mid_price=mid,
            )
            # 1m: strong directional move proportional to strength
            tracker.on_trade(
                symbol="BTCUSD",
                timestamp_ms=i * 1_000_000 + 61_000,
                price=mid + direction * strength * 800,
            )
            # 5m: reverts toward midpoint with noise that breaks correlation
            noise = ((-1) ** i) * 200  # alternating noise degrades IC
            tracker.on_trade(
                symbol="BTCUSD",
                timestamp_ms=i * 1_000_000 + 301_000,
                price=mid + direction * strength * 80 + noise,
            )

        result = tracker.get_alpha_decay_data()
        ic_1m = result["horizons"][0]["ic"]
        ic_5m = result["horizons"][1]["ic"]
        assert ic_1m is not None
        assert ic_5m is not None
        assert ic_1m > ic_5m  # IC decays

    # --- get_alpha_decay_data shape ---

    def test_get_alpha_decay_data_shape(self):
        tracker = self._make_tracker(horizons_ms=[60_000, 300_000])
        result = tracker.get_alpha_decay_data()
        assert "horizons" in result
        assert "total_signals" in result
        assert "strategies" in result
        assert len(result["horizons"]) == 2
        assert result["horizons"][0]["horizon_label"] == "1m"
        assert result["horizons"][1]["horizon_label"] == "5m"

    def test_get_alpha_decay_data_with_signals_and_trades(self):
        tracker = self._make_tracker(horizons_ms=[60_000])
        for i in range(10):
            strength = 0.1 * (i + 1)
            tracker.record_signal(
                signal_id=f"s{i}",
                timestamp_ms=i * 1_000_000,
                strategy_id="strat_a",
                symbol="BTCUSD",
                side="BUY",
                strength=strength,
                mid_price=50_000.0,
            )
            tracker.on_trade(
                symbol="BTCUSD",
                timestamp_ms=i * 1_000_000 + 61_000,
                price=50_000.0 + strength * 500,
            )

        result = tracker.get_alpha_decay_data()
        assert result["total_signals"] == 10
        assert "strat_a" in result["strategies"]
        h = result["horizons"][0]
        assert h["filled_count"] == 10
        assert h["ic"] is not None

    # --- Per-Strategy IC ---

    def test_per_strategy_ic(self):
        tracker = self._make_tracker(horizons_ms=[60_000])

        # Strategy A: good signal — stronger BUY → bigger price increase
        for i in range(10):
            strength = 0.1 * (i + 1)
            tracker.record_signal(
                signal_id=f"a{i}",
                timestamp_ms=i * 1_000_000,
                strategy_id="good_strat",
                symbol="BTCUSD",
                side="BUY",
                strength=strength,
                mid_price=50_000.0,
            )
            tracker.on_trade(
                symbol="BTCUSD",
                timestamp_ms=i * 1_000_000 + 61_000,
                price=50_000.0 + strength * 1000,
            )

        # Strategy B: bad signal — stronger BUY → bigger price decrease
        for i in range(10):
            strength = 0.1 * (i + 1)
            tracker.record_signal(
                signal_id=f"b{i}",
                timestamp_ms=(i + 20) * 1_000_000,
                strategy_id="bad_strat",
                symbol="BTCUSD",
                side="BUY",
                strength=strength,
                mid_price=50_000.0,
            )
            tracker.on_trade(
                symbol="BTCUSD",
                timestamp_ms=(i + 20) * 1_000_000 + 61_000,
                price=50_000.0 - strength * 1000,
            )

        result = tracker.get_alpha_decay_data()
        strats = result["strategies"]
        assert strats["good_strat"]["horizons"][0]["ic"] == pytest.approx(1.0, abs=0.01)
        assert strats["bad_strat"]["horizons"][0]["ic"] == pytest.approx(-1.0, abs=0.01)

    # --- Horizon label formatting ---

    def test_horizon_labels(self):
        tracker = AlphaDecayTracker(
            horizons_ms=[60_000, 300_000, 900_000, 1_800_000, 3_600_000],
        )
        result = tracker.get_alpha_decay_data()
        labels = [h["horizon_label"] for h in result["horizons"]]
        assert labels == ["1m", "5m", "15m", "30m", "1h"]
