"""In-memory state store for the post-trade service.

Accumulates fills, computes running PnL, equity curve, and TCA results.
All state lives here and is consumed by both the Kafka consumer and the
FastAPI dashboard endpoints.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from post_trade_svc.metrics import (
    compute_calmar,
    compute_max_drawdown,
    compute_sharpe,
    compute_sortino,
)
from post_trade_svc.pnl import PortfolioPnL
from post_trade_svc.tca import TCAResult, analyze_fill

logger = logging.getLogger(__name__)

# Initial portfolio equity for paper trading
INITIAL_EQUITY = 100_000.0


@dataclass
class FillRecord:
    """Stored fill with metadata for analysis."""

    fill_id: str = ""
    timestamp: int = 0
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    fill_price: float = 0.0
    fee: float = 0.0
    slippage_bps: float = 0.0
    strategy_id: str = ""
    decision_price: float = 0.0  # mid_price_at_signal from the original signal


@dataclass
class EquitySnapshot:
    """Point-in-time equity snapshot."""

    timestamp: int = 0
    equity: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class PostTradeState:
    """Thread-safe state store for all post-trade analytics."""

    def __init__(self, initial_equity: float = INITIAL_EQUITY):
        self._lock = threading.Lock()
        self._initial_equity = initial_equity

        # Core state
        self._portfolio = PortfolioPnL()
        self._fills: list[FillRecord] = []
        self._tca_results: list[TCAResult] = []
        self._equity_curve: list[EquitySnapshot] = []
        self._daily_returns: list[float] = []

        # Latest prices per symbol (for unrealized PnL)
        self._latest_prices: dict[str, float] = {}

        # Running counters
        self._total_fills = 0
        self._winning_fills = 0
        self._gross_profit = 0.0
        self._gross_loss = 0.0

        # Peak equity for drawdown
        self._peak_equity = initial_equity

    def process_fill(self, fill: FillRecord) -> None:
        """Process a new fill: update PnL, TCA, equity curve."""
        with self._lock:
            # Update position and PnL
            pos = self._portfolio.get_or_create(fill.symbol)
            realized = pos.apply_fill(
                quantity=fill.quantity,
                price=fill.fill_price,
                fee=fill.fee,
                side=fill.side,
            )

            # Track win/loss
            self._total_fills += 1
            if realized > 0:
                self._winning_fills += 1
                self._gross_profit += realized
            elif realized < 0:
                self._gross_loss += abs(realized)

            # TCA
            arrival_price = self._latest_prices.get(fill.symbol, fill.fill_price)
            tca = analyze_fill(
                fill_id=fill.fill_id,
                symbol=fill.symbol,
                side=fill.side,
                decision_price=fill.decision_price or arrival_price,
                arrival_price=arrival_price,
                fill_price=fill.fill_price,
                fee=fill.fee,
                quantity=fill.quantity,
            )
            self._tca_results.append(tca)
            self._fills.append(fill)

            # Update equity curve
            equity = self._compute_equity()
            self._equity_curve.append(
                EquitySnapshot(
                    timestamp=fill.timestamp,
                    equity=equity,
                    realized_pnl=self._portfolio.total_realized_pnl,
                    unrealized_pnl=self._portfolio.total_unrealized_pnl(self._latest_prices),
                )
            )

            # Update peak equity
            if equity > self._peak_equity:
                self._peak_equity = equity

            # Daily return (simplified: per-fill return)
            if len(self._equity_curve) >= 2:
                prev = self._equity_curve[-2].equity
                if prev > 0:
                    self._daily_returns.append((equity - prev) / prev)

    def update_price(self, symbol: str, price: float) -> None:
        """Update latest price for unrealized PnL computation."""
        with self._lock:
            self._latest_prices[symbol] = price

    def _compute_equity(self) -> float:
        """Current total equity."""
        return (
            self._initial_equity
            + self._portfolio.total_realized_pnl
            + self._portfolio.total_unrealized_pnl(self._latest_prices)
            - self._portfolio.total_fees
        )

    # -----------------------------------------------------------------------
    # Dashboard data methods (all thread-safe)
    # -----------------------------------------------------------------------

    def get_pnl_summary(self) -> dict:
        """Tab 1: PnL attribution."""
        with self._lock:
            equity = self._compute_equity()
            positions = {}
            for sym, pos in self._portfolio.positions.items():
                current_price = self._latest_prices.get(sym, pos.avg_entry_price)
                positions[sym] = {
                    "quantity": pos.quantity,
                    "avg_entry_price": round(pos.avg_entry_price, 2),
                    "realized_pnl": round(pos.realized_pnl, 2),
                    "unrealized_pnl": round(pos.unrealized_pnl(current_price), 2),
                    "total_fees": round(pos.total_fees, 4),
                    "current_price": round(current_price, 2),
                }

            return {
                "initial_equity": self._initial_equity,
                "current_equity": round(equity, 2),
                "total_realized_pnl": round(self._portfolio.total_realized_pnl, 2),
                "total_unrealized_pnl": round(self._portfolio.total_unrealized_pnl(self._latest_prices), 2),
                "total_fees": round(self._portfolio.total_fees, 4),
                "total_return_pct": round((equity - self._initial_equity) / self._initial_equity * 100, 4),
                "positions": positions,
                "num_fills": self._total_fills,
            }

    def get_tca_summary(self) -> dict:
        """Tab 2: Transaction cost analysis."""
        with self._lock:
            if not self._tca_results:
                return {"fills": [], "averages": {}}

            avg_spread = sum(t.spread_cost_bps for t in self._tca_results) / len(self._tca_results)
            avg_slippage = sum(t.slippage_bps for t in self._tca_results) / len(self._tca_results)
            avg_impact = sum(t.market_impact_bps for t in self._tca_results) / len(self._tca_results)
            avg_fee = sum(t.fee_bps for t in self._tca_results) / len(self._tca_results)
            avg_total = sum(t.total_cost_bps for t in self._tca_results) / len(self._tca_results)

            fills = [
                {
                    "fill_id": t.fill_id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "spread_cost_bps": round(t.spread_cost_bps, 2),
                    "slippage_bps": round(t.slippage_bps, 2),
                    "market_impact_bps": round(t.market_impact_bps, 2),
                    "fee_bps": round(t.fee_bps, 2),
                    "total_cost_bps": round(t.total_cost_bps, 2),
                }
                for t in self._tca_results[-100:]  # last 100
            ]

            return {
                "fills": fills,
                "averages": {
                    "spread_cost_bps": round(avg_spread, 2),
                    "slippage_bps": round(avg_slippage, 2),
                    "market_impact_bps": round(avg_impact, 2),
                    "fee_bps": round(avg_fee, 2),
                    "total_cost_bps": round(avg_total, 2),
                },
                "num_fills": len(self._tca_results),
            }

    def get_risk_metrics(self) -> dict:
        """Tab 4: Sharpe, Sortino, Calmar, etc."""
        with self._lock:
            equity = self._compute_equity()
            returns = self._daily_returns[-365:]  # last year of returns

            sharpe = compute_sharpe(returns)
            sortino = compute_sortino(returns)
            equity_values = [s.equity for s in self._equity_curve]
            max_dd, max_dd_dur = compute_max_drawdown(equity_values)

            total_return = (equity - self._initial_equity) / self._initial_equity
            # Rough annualization
            n_periods = len(returns) if returns else 1
            annualized = total_return * (365 / max(n_periods, 1))
            calmar = compute_calmar(annualized, max_dd)

            win_rate = self._winning_fills / self._total_fills if self._total_fills > 0 else 0.0
            profit_factor = self._gross_profit / self._gross_loss if self._gross_loss > 0 else 0.0

            return {
                "sharpe_ratio": round(sharpe, 4),
                "sortino_ratio": round(sortino, 4) if sortino != float("inf") else "inf",
                "calmar_ratio": round(calmar, 4),
                "max_drawdown_pct": round(max_dd * 100, 4),
                "max_drawdown_duration_periods": max_dd_dur,
                "total_return_pct": round(total_return * 100, 4),
                "annualized_return_pct": round(annualized * 100, 4),
                "win_rate_pct": round(win_rate * 100, 2),
                "profit_factor": round(profit_factor, 4),
                "num_trades": self._total_fills,
                "current_equity": round(equity, 2),
                "peak_equity": round(self._peak_equity, 2),
            }

    def get_drawdown_data(self) -> dict:
        """Tab 5: Drawdown analysis."""
        with self._lock:
            if not self._equity_curve:
                return {"equity_curve": [], "drawdown_curve": [], "current_drawdown_pct": 0.0}

            equity_curve = [{"timestamp": s.timestamp, "equity": round(s.equity, 2)} for s in self._equity_curve[-500:]]

            # Compute running drawdown
            drawdown_curve = []
            peak = self._initial_equity
            for s in self._equity_curve[-500:]:
                if s.equity > peak:
                    peak = s.equity
                dd = (peak - s.equity) / peak if peak > 0 else 0.0
                drawdown_curve.append(
                    {
                        "timestamp": s.timestamp,
                        "drawdown_pct": round(dd * 100, 4),
                    }
                )

            current_dd = (
                (self._peak_equity - self._compute_equity()) / self._peak_equity if self._peak_equity > 0 else 0.0
            )

            return {
                "equity_curve": equity_curve,
                "drawdown_curve": drawdown_curve,
                "current_drawdown_pct": round(current_dd * 100, 4),
                "peak_equity": round(self._peak_equity, 2),
            }

    def get_fill_analysis(self) -> dict:
        """Tab 6: Fill rate and order lifecycle."""
        with self._lock:
            if not self._fills:
                return {"fills": [], "summary": {}}

            fills = [
                {
                    "fill_id": f.fill_id,
                    "timestamp": f.timestamp,
                    "symbol": f.symbol,
                    "side": f.side,
                    "quantity": f.quantity,
                    "fill_price": round(f.fill_price, 2),
                    "fee": round(f.fee, 4),
                    "slippage_bps": round(f.slippage_bps, 2),
                    "strategy_id": f.strategy_id,
                }
                for f in self._fills[-100:]
            ]

            buy_fills = [f for f in self._fills if f.side == "BUY"]
            sell_fills = [f for f in self._fills if f.side == "SELL"]

            return {
                "fills": fills,
                "summary": {
                    "total_fills": self._total_fills,
                    "buy_fills": len(buy_fills),
                    "sell_fills": len(sell_fills),
                    "avg_slippage_bps": round(sum(f.slippage_bps for f in self._fills) / len(self._fills), 2)
                    if self._fills
                    else 0.0,
                    "total_fees": round(self._portfolio.total_fees, 4),
                },
            }

    def get_all_data_for_export(self) -> dict:
        """All tabs combined for Excel export."""
        return {
            "pnl": self.get_pnl_summary(),
            "tca": self.get_tca_summary(),
            "risk_metrics": self.get_risk_metrics(),
            "drawdown": self.get_drawdown_data(),
            "fills": self.get_fill_analysis(),
        }
