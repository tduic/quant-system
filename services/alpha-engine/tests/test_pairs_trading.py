"""Tests for pairs trading strategy."""

from __future__ import annotations

from alpha_engine_svc.cross_asset import CrossAssetTracker
from alpha_engine_svc.strategies.pairs_trading import PairsTradingStrategy
from quant_core.models import DepthUpdate, Trade


def _make_trade(symbol: str, price: float, ts: int = 0) -> Trade:
    return Trade(
        timestamp_exchange=ts,
        timestamp_ingested=ts,
        symbol=symbol,
        trade_id=ts,
        price=price,
        quantity=0.1,
        is_buyer_maker=False,
    )


class TestPairsTradingStrategy:
    def _build_strategy(self, **kwargs) -> tuple[PairsTradingStrategy, CrossAssetTracker]:
        tracker = CrossAssetTracker(window=200)
        params = {
            "entry_threshold": 2.0,
            "min_correlation": 0.3,
            "base_quantity": 0.01,
            "cooldown_trades": 5,
            "warmup_trades": 10,
        }
        params.update(kwargs)
        strat = PairsTradingStrategy(
            strategy_id="pairs_btc_eth",
            symbol="BTCUSD",
            symbol_b="ETHUSD",
            cross_asset_tracker=tracker,
            params=params,
        )
        return strat, tracker

    def test_no_signal_during_warmup(self):
        strat, tracker = self._build_strategy(warmup_trades=50)
        for i in range(30):
            tracker.on_price("BTCUSD", i * 1000, 50000 + i)
            tracker.on_price("ETHUSD", i * 1000, 3000 + i)
            sig = strat.on_trade(_make_trade("BTCUSD", 50000 + i, i * 1000))
            assert sig is None

    def test_no_signal_without_sufficient_cross_data(self):
        """Need MIN_OBSERVATIONS in cross-asset tracker before signals."""
        strat, tracker = self._build_strategy(warmup_trades=5)
        for i in range(10):
            tracker.on_price("BTCUSD", i * 1000, 50000)
            tracker.on_price("ETHUSD", i * 1000, 3000)
            sig = strat.on_trade(_make_trade("BTCUSD", 50000, i * 1000))
        assert sig is None  # Not enough data for correlation

    def test_signal_on_spread_divergence(self):
        """When spread z-score exceeds threshold, emit signal."""
        strat, tracker = self._build_strategy(warmup_trades=5, cooldown_trades=1)

        # Build correlated history (both trending up together)
        for i in range(30):
            price_a = 50000 + i * 100
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))

        # Now cause A to spike (diverge from B) — ratio increases, z > threshold
        signals = []
        for i in range(30, 50):
            price_a = 50000 + 30 * 100 + (i - 30) * 500  # A spikes up
            price_b = 3000 + i * 6  # B continues normally
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            sig = strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))
            if sig is not None:
                signals.append(sig)

        # Should have emitted at least one signal
        assert len(signals) >= 1
        # A is expensive relative to B → SELL A
        assert signals[0].side == "SELL"
        assert signals[0].symbol == "BTCUSD"
        assert "pair" in signals[0].metadata
        assert signals[0].metadata["leg"] == "A"

    def test_counterpart_signal(self):
        """When leg A signal fires, counterpart for B should be available."""
        strat, tracker = self._build_strategy(warmup_trades=5, cooldown_trades=1)

        # Build history then diverge
        for i in range(30):
            price_a = 50000 + i * 100
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))

        # Diverge A upward
        sig_a = None
        for i in range(30, 50):
            price_a = 50000 + 30 * 100 + (i - 30) * 500
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            result = strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))
            if result is not None:
                sig_a = result
                break

        if sig_a is not None:
            counterpart = strat.get_counterpart_signal()
            assert counterpart is not None
            assert counterpart.symbol == "ETHUSD"
            # Opposite side from A
            assert counterpart.side != sig_a.side
            assert counterpart.metadata["leg"] == "B"

            # Second call should return None (consumed)
            assert strat.get_counterpart_signal() is None

    def test_no_duplicate_signals_same_direction(self):
        """Shouldn't emit same-direction signals twice in a row."""
        strat, tracker = self._build_strategy(warmup_trades=5, cooldown_trades=1)

        for i in range(30):
            price_a = 50000 + i * 100
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))

        signals = []
        for i in range(30, 80):
            price_a = 50000 + 30 * 100 + (i - 30) * 500
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            sig = strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))
            if sig:
                signals.append(sig)

        # No two consecutive signals should have the same side
        for i in range(1, len(signals)):
            assert signals[i].side != signals[i - 1].side

    def test_cooldown_respected(self):
        """No signals within cooldown period."""
        strat, tracker = self._build_strategy(warmup_trades=5, cooldown_trades=100)

        for i in range(30):
            price_a = 50000 + i * 100
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))

        signal_count = 0
        for i in range(30, 80):
            price_a = 50000 + 30 * 100 + (i - 30) * 500
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            sig = strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))
            if sig:
                signal_count += 1

        # With cooldown=100 and only 50 trades after warmup, at most 1 signal
        assert signal_count <= 1

    def test_low_correlation_no_signal(self):
        """If correlation is below threshold, don't trade."""
        strat, tracker = self._build_strategy(warmup_trades=5, cooldown_trades=1, min_correlation=0.99)

        import random

        random.seed(123)
        # Uncorrelated random walks
        price_a = 50000.0
        price_b = 3000.0
        for i in range(50):
            price_a *= 1 + random.gauss(0, 0.02)
            price_b *= 1 + random.gauss(0, 0.02)
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            sig = strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))

        # Low correlation should mean no signals emitted
        # (last sig should be None)
        assert sig is None

    def test_book_update_returns_none(self):
        strat, _ = self._build_strategy()
        depth = DepthUpdate(
            timestamp_exchange=1000,
            timestamp_ingested=1000,
            symbol="BTCUSD",
            bids=[[50000.0, 1.0]],
            asks=[[50001.0, 1.0]],
        )
        assert strat.on_book_update(depth) is None

    def test_strategy_properties(self):
        strat, _ = self._build_strategy()
        assert strat.symbol == "BTCUSD"
        assert strat.symbol_b == "ETHUSD"
        assert strat.strategy_id == "pairs_btc_eth"

    def test_signal_metadata_contains_pair_info(self):
        """Emitted signal metadata should contain pair, z_score, correlation."""
        strat, tracker = self._build_strategy(warmup_trades=5, cooldown_trades=1)

        for i in range(30):
            price_a = 50000 + i * 100
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))

        for i in range(30, 60):
            price_a = 50000 + 30 * 100 + (i - 30) * 500
            price_b = 3000 + i * 6
            tracker.on_price("BTCUSD", i * 1000, price_a)
            tracker.on_price("ETHUSD", i * 1000, price_b)
            sig = strat.on_trade(_make_trade("BTCUSD", price_a, i * 1000))
            if sig is not None:
                assert "pair" in sig.metadata
                assert "z_score" in sig.metadata
                assert "correlation" in sig.metadata
                assert sig.metadata["pair"] == "BTCUSD/ETHUSD"
                break
