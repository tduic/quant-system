"""FastAPI dashboard with 6 tabs + Excel export.

Each tab has its own GET endpoint returning JSON. The Excel export
bundles all tabs into a single workbook with separate sheets.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from post_trade_svc.state import PostTradeState

logger = logging.getLogger(__name__)


def create_app(state: PostTradeState) -> FastAPI:
    """Create the FastAPI app with all dashboard endpoints."""

    app = FastAPI(
        title="Quant Post-Trade Dashboard",
        description="Real-time post-trade analytics",
        version="0.1.0",
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # Tab 1: PnL Attribution
    @app.get("/api/pnl")
    def pnl_summary():
        return state.get_pnl_summary()

    # Tab 2: Transaction Cost Analysis
    @app.get("/api/tca")
    def tca_summary():
        return state.get_tca_summary()

    # Tab 3: Alpha Decay (placeholder — needs signal-level IC tracking)
    @app.get("/api/alpha-decay")
    def alpha_decay():
        return {
            "status": "placeholder",
            "description": "Alpha decay curves require signal-level IC tracking. Coming in Phase 5 (backtesting).",
        }

    # Tab 4: Risk Metrics
    @app.get("/api/risk-metrics")
    def risk_metrics():
        return state.get_risk_metrics()

    # Tab 5: Drawdown Analysis
    @app.get("/api/drawdown")
    def drawdown():
        return state.get_drawdown_data()

    # Tab 6: Fill Analysis
    @app.get("/api/fills")
    def fill_analysis():
        return state.get_fill_analysis()

    # Excel Export
    @app.get("/api/export/excel")
    def export_excel():
        data = state.get_all_data_for_export()
        workbook_bytes = _build_excel(data)
        return StreamingResponse(
            io.BytesIO(workbook_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=post_trade_report.xlsx"},
        )

    return app


def _build_excel(data: dict) -> bytes:
    """Build an Excel workbook with one sheet per tab."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    header_font = Font(bold=True, size=12)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font_white = Font(bold=True, size=11, color="FFFFFF")

    def write_header(ws, headers: list[str], row: int = 1) -> None:
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col, value=h)
            cell.font = header_font_white
            cell.fill = header_fill

    # --- Sheet 1: PnL Summary ---
    ws_pnl = wb.active
    ws_pnl.title = "PnL Summary"
    pnl = data["pnl"]
    summary_rows = [
        ("Initial Equity", pnl["initial_equity"]),
        ("Current Equity", pnl["current_equity"]),
        ("Total Realized PnL", pnl["total_realized_pnl"]),
        ("Total Unrealized PnL", pnl["total_unrealized_pnl"]),
        ("Total Fees", pnl["total_fees"]),
        ("Total Return %", pnl["total_return_pct"]),
        ("Number of Fills", pnl["num_fills"]),
    ]
    write_header(ws_pnl, ["Metric", "Value"])
    for i, (metric, value) in enumerate(summary_rows, 2):
        ws_pnl.cell(row=i, column=1, value=metric)
        ws_pnl.cell(row=i, column=2, value=value)

    # Positions
    if pnl["positions"]:
        row = len(summary_rows) + 4
        ws_pnl.cell(row=row - 1, column=1, value="Positions").font = header_font
        write_header(ws_pnl, ["Symbol", "Quantity", "Avg Entry", "Realized PnL", "Unrealized PnL", "Fees"], row)
        for sym, pos in pnl["positions"].items():
            row += 1
            ws_pnl.cell(row=row, column=1, value=sym)
            ws_pnl.cell(row=row, column=2, value=pos["quantity"])
            ws_pnl.cell(row=row, column=3, value=pos["avg_entry_price"])
            ws_pnl.cell(row=row, column=4, value=pos["realized_pnl"])
            ws_pnl.cell(row=row, column=5, value=pos["unrealized_pnl"])
            ws_pnl.cell(row=row, column=6, value=pos["total_fees"])

    ws_pnl.column_dimensions["A"].width = 22
    ws_pnl.column_dimensions["B"].width = 18

    # --- Sheet 2: TCA ---
    ws_tca = wb.create_sheet("TCA")
    tca = data["tca"]
    if tca.get("fills"):
        headers = [
            "Fill ID",
            "Symbol",
            "Side",
            "Spread (bps)",
            "Slippage (bps)",
            "Market Impact (bps)",
            "Fee (bps)",
            "Total Cost (bps)",
        ]
        write_header(ws_tca, headers)
        for i, f in enumerate(tca["fills"], 2):
            ws_tca.cell(row=i, column=1, value=f["fill_id"][:12])
            ws_tca.cell(row=i, column=2, value=f["symbol"])
            ws_tca.cell(row=i, column=3, value=f["side"])
            ws_tca.cell(row=i, column=4, value=f["spread_cost_bps"])
            ws_tca.cell(row=i, column=5, value=f["slippage_bps"])
            ws_tca.cell(row=i, column=6, value=f["market_impact_bps"])
            ws_tca.cell(row=i, column=7, value=f["fee_bps"])
            ws_tca.cell(row=i, column=8, value=f["total_cost_bps"])

        # Averages row
        row = len(tca["fills"]) + 3
        ws_tca.cell(row=row, column=1, value="AVERAGES").font = header_font
        avgs = tca["averages"]
        ws_tca.cell(row=row, column=4, value=avgs["spread_cost_bps"])
        ws_tca.cell(row=row, column=5, value=avgs["slippage_bps"])
        ws_tca.cell(row=row, column=6, value=avgs["market_impact_bps"])
        ws_tca.cell(row=row, column=7, value=avgs["fee_bps"])
        ws_tca.cell(row=row, column=8, value=avgs["total_cost_bps"])

    # --- Sheet 3: Risk Metrics ---
    ws_risk = wb.create_sheet("Risk Metrics")
    metrics = data["risk_metrics"]
    write_header(ws_risk, ["Metric", "Value"])
    metric_rows = [
        ("Sharpe Ratio", metrics["sharpe_ratio"]),
        ("Sortino Ratio", metrics["sortino_ratio"]),
        ("Calmar Ratio", metrics["calmar_ratio"]),
        ("Max Drawdown %", metrics["max_drawdown_pct"]),
        ("Max DD Duration (periods)", metrics["max_drawdown_duration_periods"]),
        ("Total Return %", metrics["total_return_pct"]),
        ("Annualized Return %", metrics["annualized_return_pct"]),
        ("Win Rate %", metrics["win_rate_pct"]),
        ("Profit Factor", metrics["profit_factor"]),
        ("Number of Trades", metrics["num_trades"]),
        ("Current Equity", metrics["current_equity"]),
        ("Peak Equity", metrics["peak_equity"]),
    ]
    for i, (metric, value) in enumerate(metric_rows, 2):
        ws_risk.cell(row=i, column=1, value=metric)
        ws_risk.cell(row=i, column=2, value=value)
    ws_risk.column_dimensions["A"].width = 28
    ws_risk.column_dimensions["B"].width = 18

    # --- Sheet 4: Drawdown ---
    ws_dd = wb.create_sheet("Drawdown")
    dd = data["drawdown"]
    write_header(ws_dd, ["Timestamp", "Equity", "Drawdown %"])
    for i, (eq, ddc) in enumerate(zip(dd["equity_curve"], dd["drawdown_curve"], strict=False), 2):
        ws_dd.cell(row=i, column=1, value=eq["timestamp"])
        ws_dd.cell(row=i, column=2, value=eq["equity"])
        ws_dd.cell(row=i, column=3, value=ddc["drawdown_pct"])

    # --- Sheet 5: Fills ---
    ws_fills = wb.create_sheet("Fills")
    fills = data["fills"]
    if fills.get("fills"):
        headers = ["Fill ID", "Timestamp", "Symbol", "Side", "Quantity", "Price", "Fee", "Slippage (bps)", "Strategy"]
        write_header(ws_fills, headers)
        for i, f in enumerate(fills["fills"], 2):
            ws_fills.cell(row=i, column=1, value=f["fill_id"][:12])
            ws_fills.cell(row=i, column=2, value=f["timestamp"])
            ws_fills.cell(row=i, column=3, value=f["symbol"])
            ws_fills.cell(row=i, column=4, value=f["side"])
            ws_fills.cell(row=i, column=5, value=f["quantity"])
            ws_fills.cell(row=i, column=6, value=f["fill_price"])
            ws_fills.cell(row=i, column=7, value=f["fee"])
            ws_fills.cell(row=i, column=8, value=f["slippage_bps"])
            ws_fills.cell(row=i, column=9, value=f["strategy_id"])

    # Save to bytes
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
