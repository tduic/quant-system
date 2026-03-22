"""Tests for post_trade_svc.dashboard — FastAPI endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from post_trade_svc.dashboard import _build_excel, create_app
from post_trade_svc.state import FillRecord, PostTradeState


@pytest.fixture
def state() -> PostTradeState:
    return PostTradeState(initial_equity=100_000.0)


@pytest.fixture
def client(state: PostTradeState) -> TestClient:
    app = create_app(state)
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestPnLEndpoint:
    def test_empty_pnl(self, client: TestClient):
        resp = client.get("/api/pnl")
        assert resp.status_code == 200
        data = resp.json()
        assert data["initial_equity"] == 100_000.0
        assert data["num_fills"] == 0

    def test_pnl_after_fill(self, client: TestClient, state: PostTradeState):
        state.process_fill(
            FillRecord(
                fill_id="f1",
                symbol="BTCUSD",
                side="BUY",
                quantity=0.001,
                fill_price=80_000.0,
                fee=0.48,
                timestamp=1000,
                strategy_id="test",
            )
        )
        resp = client.get("/api/pnl")
        data = resp.json()
        assert data["num_fills"] == 1
        assert "BTCUSD" in data["positions"]


class TestTCAEndpoint:
    def test_empty_tca(self, client: TestClient):
        resp = client.get("/api/tca")
        assert resp.status_code == 200
        assert resp.json()["fills"] == []

    def test_tca_after_fill(self, client: TestClient, state: PostTradeState):
        state.update_price("BTCUSD", 80_000.0)
        state.process_fill(
            FillRecord(
                fill_id="f1",
                symbol="BTCUSD",
                side="BUY",
                quantity=0.001,
                fill_price=80_001.0,
                fee=0.48,
                timestamp=1000,
                strategy_id="test",
            )
        )
        resp = client.get("/api/tca")
        data = resp.json()
        assert data["num_fills"] == 1


class TestAlphaDecayEndpoint:
    def test_returns_placeholder(self, client: TestClient):
        resp = client.get("/api/alpha-decay")
        assert resp.status_code == 200
        assert resp.json()["status"] == "placeholder"


class TestRiskMetricsEndpoint:
    def test_empty_metrics(self, client: TestClient):
        resp = client.get("/api/risk-metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["num_trades"] == 0


class TestDrawdownEndpoint:
    def test_empty_drawdown(self, client: TestClient):
        resp = client.get("/api/drawdown")
        assert resp.status_code == 200
        data = resp.json()
        assert data["equity_curve"] == []


class TestFillsEndpoint:
    def test_empty_fills(self, client: TestClient):
        resp = client.get("/api/fills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fills"] == []


class TestExcelExport:
    def test_excel_endpoint_returns_xlsx(self, client: TestClient):
        resp = client.get("/api/export/excel")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]
        assert len(resp.content) > 0

    def test_excel_with_data(self, client: TestClient, state: PostTradeState):
        state.update_price("BTCUSD", 80_000.0)
        state.process_fill(
            FillRecord(
                fill_id="f1",
                symbol="BTCUSD",
                side="BUY",
                quantity=0.001,
                fill_price=80_000.0,
                fee=0.48,
                timestamp=1000,
                strategy_id="test",
            )
        )
        resp = client.get("/api/export/excel")
        assert resp.status_code == 200
        assert len(resp.content) > 100  # actual workbook data

    def test_build_excel_returns_bytes(self, state: PostTradeState):
        data = state.get_all_data_for_export()
        wb_bytes = _build_excel(data)
        assert isinstance(wb_bytes, bytes)
        assert len(wb_bytes) > 0
