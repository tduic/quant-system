"""Tests for risk_gateway_svc.var_model — parametric VaR."""

from __future__ import annotations

import pytest

from risk_gateway_svc.var_model import Z_SCORES, ParametricVaR


@pytest.fixture
def var_model() -> ParametricVaR:
    return ParametricVaR(window_size=100, confidence=0.95, horizon_hours=1.0)


class TestVaRBasics:
    def test_insufficient_data_returns_zero_var(self, var_model: ParametricVaR):
        for i in range(5):
            var_model.update(100.0, i * 1000)
        result = var_model.compute(100_000.0)
        assert result.var_amount == 0.0
        assert result.n_observations == 5

    def test_constant_price_zero_var(self, var_model: ParametricVaR):
        for i in range(50):
            var_model.update(100.0, i * 60_000)
        result = var_model.compute(100_000.0)
        # Constant price => zero volatility => zero VaR
        assert result.var_amount == pytest.approx(0.0, abs=0.01)
        assert result.volatility == pytest.approx(0.0, abs=0.001)

    def test_volatile_price_positive_var(self, var_model: ParametricVaR):
        # Alternating prices create volatility
        for i in range(50):
            price = 100.0 + (-1) ** i * 2.0  # 98, 102, 98, 102...
            var_model.update(price, i * 60_000)
        result = var_model.compute(100_000.0)
        assert result.var_amount > 0
        assert result.volatility > 0

    def test_higher_confidence_higher_var(self):
        model_95 = ParametricVaR(confidence=0.95)
        model_99 = ParametricVaR(confidence=0.99)
        for i in range(50):
            price = 100.0 + (-1) ** i * 2.0
            model_95.update(price, i * 60_000)
            model_99.update(price, i * 60_000)
        var_95 = model_95.compute(100_000.0)
        var_99 = model_99.compute(100_000.0)
        assert var_99.var_amount > var_95.var_amount

    def test_larger_portfolio_larger_var(self, var_model: ParametricVaR):
        for i in range(50):
            price = 100.0 + (-1) ** i * 2.0
            var_model.update(price, i * 60_000)
        var_small = var_model.compute(10_000.0)
        var_large = var_model.compute(100_000.0)
        assert var_large.var_amount > var_small.var_amount


class TestVaRResult:
    def test_result_has_all_fields(self, var_model: ParametricVaR):
        for i in range(50):
            var_model.update(100.0 + i * 0.1, i * 60_000)
        result = var_model.compute(100_000.0)
        assert result.confidence == 0.95
        assert result.horizon_hours == 1.0
        assert result.n_observations == 50
        assert isinstance(result.volatility, float)
        assert isinstance(result.drift, float)

    def test_var_pct_consistent_with_amount(self, var_model: ParametricVaR):
        for i in range(50):
            price = 100.0 + (-1) ** i * 2.0
            var_model.update(price, i * 60_000)
        pv = 100_000.0
        result = var_model.compute(pv)
        if result.var_amount > 0:
            assert result.var_amount == pytest.approx(pv * result.var_pct, rel=0.01)


class TestZScores:
    def test_z_scores_exist(self):
        assert 0.90 in Z_SCORES
        assert 0.95 in Z_SCORES
        assert 0.99 in Z_SCORES

    def test_z_scores_ordered(self):
        assert Z_SCORES[0.90] < Z_SCORES[0.95] < Z_SCORES[0.99]


class TestVaRHorizon:
    def test_longer_horizon_higher_var(self):
        model_1h = ParametricVaR(confidence=0.95, horizon_hours=1.0)
        model_24h = ParametricVaR(confidence=0.95, horizon_hours=24.0)
        for i in range(50):
            price = 100.0 + (-1) ** i * 2.0
            model_1h.update(price, i * 60_000)
            model_24h.update(price, i * 60_000)
        var_1h = model_1h.compute(100_000.0)
        var_24h = model_24h.compute(100_000.0)
        assert var_24h.var_amount > var_1h.var_amount
