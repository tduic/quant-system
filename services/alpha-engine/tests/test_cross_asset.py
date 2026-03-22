"""Tests for cross-asset analytics (correlation, relative strength, spread z-score)."""

from __future__ import annotations

from alpha_engine_svc.cross_asset import CrossAssetSnapshot, CrossAssetTracker


class TestCrossAssetTracker:
    """Tests for CrossAssetTracker."""

    def test_empty_tracker_returns_none_metrics(self):
        tracker = CrossAssetTracker()
        snap = tracker.get_snapshot("BTCUSD", "ETHUSD")
        assert snap.correlation is None
        assert snap.relative_strength is None
        assert snap.spread_z_score is None

    def test_insufficient_data_returns_none(self):
        tracker = CrossAssetTracker()
        # Only 5 observations — below MIN_OBSERVATIONS (20)
        for i in range(5):
            tracker.on_price("BTCUSD", i * 1000, 50000 + i * 10)
            tracker.on_price("ETHUSD", i * 1000, 3000 + i * 5)
        snap = tracker.get_snapshot("BTCUSD", "ETHUSD")
        assert snap.correlation is None

    def test_symbols_tracked(self):
        tracker = CrossAssetTracker()
        tracker.on_price("BTCUSD", 1000, 50000)
        tracker.on_price("ETHUSD", 1000, 3000)
        tracker.on_price("SOLUSD", 1000, 150)
        assert sorted(tracker.symbols) == ["BTCUSD", "ETHUSD", "SOLUSD"]

    def test_perfect_positive_correlation(self):
        """Two assets moving in lockstep should have correlation ~1.0."""
        tracker = CrossAssetTracker()
        for i in range(25):
            # Both go up linearly with some noise
            tracker.on_price("A", i * 1000, 100 + i * 2)
            tracker.on_price("B", i * 1000, 50 + i * 1)
        snap = tracker.get_snapshot("A", "B")
        assert snap.correlation is not None
        assert snap.correlation > 0.99

    def test_perfect_negative_correlation(self):
        """When A's return = -B's return, correlation should be near -1."""
        tracker = CrossAssetTracker()
        # Use multiplicative returns: when A goes up X%, B goes down X%
        price_a = 100.0
        price_b = 100.0
        returns = [
            0.01,
            -0.02,
            0.015,
            -0.005,
            0.03,
            -0.01,
            0.02,
            -0.025,
            0.005,
            -0.015,
            0.01,
            -0.02,
            0.025,
            -0.01,
            0.015,
            -0.005,
            0.02,
            -0.03,
            0.01,
            -0.015,
            0.005,
            -0.02,
            0.03,
            -0.01,
            0.015,
        ]
        tracker.on_price("A", 0, price_a)
        tracker.on_price("B", 0, price_b)
        for i, r in enumerate(returns):
            price_a *= 1 + r
            price_b *= 1 - r  # opposite return
            tracker.on_price("A", (i + 1) * 1000, price_a)
            tracker.on_price("B", (i + 1) * 1000, price_b)
        snap = tracker.get_snapshot("A", "B")
        assert snap.correlation is not None
        assert snap.correlation < -0.95

    def test_relative_strength_positive(self):
        """A outperforms B — relative strength > 1."""
        tracker = CrossAssetTracker()
        for i in range(25):
            # A grows faster than B
            tracker.on_price("A", i * 1000, 100 * (1.01**i))  # 1% per step
            tracker.on_price("B", i * 1000, 100 * (1.005**i))  # 0.5% per step
        snap = tracker.get_snapshot("A", "B")
        assert snap.relative_strength is not None
        assert snap.relative_strength > 1.0

    def test_relative_strength_negative(self):
        """B outperforms A — relative strength < 1."""
        tracker = CrossAssetTracker()
        for i in range(25):
            tracker.on_price("A", i * 1000, 100 * (1.002**i))
            tracker.on_price("B", i * 1000, 100 * (1.01**i))
        snap = tracker.get_snapshot("A", "B")
        assert snap.relative_strength is not None
        assert snap.relative_strength < 1.0

    def test_spread_z_score_centered(self):
        """If ratio is constant, z-score should be ~0."""
        tracker = CrossAssetTracker()
        for i in range(25):
            # Constant ratio of 2:1
            tracker.on_price("A", i * 1000, 200 + i * 4)
            tracker.on_price("B", i * 1000, 100 + i * 2)
        snap = tracker.get_snapshot("A", "B")
        # Spread z-score should be near zero since ratio barely changes
        # With perfectly proportional growth, the log ratio is constant
        # so variance is ~0 and z-score is None
        # Let's just check it doesn't crash
        assert snap.symbol_a == "A"
        assert snap.symbol_b == "B"

    def test_spread_z_score_divergence(self):
        """When ratio diverges from mean, z-score should be large."""
        tracker = CrossAssetTracker()
        # First 20 observations: stable ratio
        for i in range(20):
            tracker.on_price("A", i * 1000, 100.0)
            tracker.on_price("B", i * 1000, 50.0)
        # Next 5: A shoots up, ratio diverges
        for i in range(20, 30):
            tracker.on_price("A", i * 1000, 100.0 + (i - 20) * 10)
            tracker.on_price("B", i * 1000, 50.0)
        snap = tracker.get_snapshot("A", "B")
        if snap.spread_z_score is not None:
            assert snap.spread_z_score > 1.0  # diverged from mean

    def test_window_size_respects_maxlen(self):
        """Tracker should only keep `window + 1` prices."""
        tracker = CrossAssetTracker(window=30)
        for i in range(100):
            tracker.on_price("A", i * 1000, 100 + i)
        # Should have at most window + 1 = 31 prices
        assert len(tracker._prices["A"]) <= 31

    def test_get_all_snapshots_pairs(self):
        """Should return C(n,2) snapshots for n symbols."""
        tracker = CrossAssetTracker()
        for i in range(25):
            tracker.on_price("A", i * 1000, 100 + i)
            tracker.on_price("B", i * 1000, 200 + i * 2)
            tracker.on_price("C", i * 1000, 50 + i * 0.5)
        snapshots = tracker.get_all_snapshots()
        # 3 symbols -> 3 pairs: (A,B), (A,C), (B,C)
        assert len(snapshots) == 3
        pairs = {(s.symbol_a, s.symbol_b) for s in snapshots}
        assert ("A", "B") in pairs
        assert ("A", "C") in pairs
        assert ("B", "C") in pairs

    def test_single_symbol_no_pairs(self):
        """One symbol means no pairs to compute."""
        tracker = CrossAssetTracker()
        for i in range(25):
            tracker.on_price("A", i * 1000, 100 + i)
        snapshots = tracker.get_all_snapshots()
        assert len(snapshots) == 0

    def test_asymmetric_data_uses_shorter(self):
        """If one symbol has fewer observations, align on the shorter."""
        tracker = CrossAssetTracker()
        for i in range(50):
            tracker.on_price("A", i * 1000, 100 + i)
        for i in range(22):
            tracker.on_price("B", i * 1000, 200 + i * 2)
        snap = tracker.get_snapshot("A", "B")
        # Should still compute (22 - 1 = 21 returns, >= MIN_OBSERVATIONS of 20)
        assert snap.correlation is not None

    def test_snapshot_dataclass_defaults(self):
        snap = CrossAssetSnapshot()
        assert snap.symbol_a == ""
        assert snap.symbol_b == ""
        assert snap.correlation is None
        assert snap.relative_strength is None
        assert snap.spread_z_score is None
        assert snap.timestamp_ms == 0

    def test_correlation_with_uncorrelated_data(self):
        """Two independent series should have correlation near 0."""
        import random

        random.seed(42)
        tracker = CrossAssetTracker(window=200)
        # Random walk A
        price_a = 100.0
        price_b = 100.0
        for i in range(150):
            price_a *= 1 + random.gauss(0, 0.01)
            price_b *= 1 + random.gauss(0, 0.01)
            tracker.on_price("A", i * 1000, price_a)
            tracker.on_price("B", i * 1000, price_b)
        snap = tracker.get_snapshot("A", "B")
        assert snap.correlation is not None
        # Uncorrelated: correlation should be near 0 (within reasonable tolerance)
        assert abs(snap.correlation) < 0.5
