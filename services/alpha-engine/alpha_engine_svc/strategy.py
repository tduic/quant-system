"""Base strategy interface and registry.

All strategies inherit from BaseStrategy and implement on_trade() and
on_book_update(). The strategy registry manages active strategies and
routes market data events to them.
"""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quant_core.models import DepthUpdate, Signal, Trade

logger = logging.getLogger(__name__)


class BaseStrategy(abc.ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, strategy_id: str, symbol: str, params: dict[str, Any] | None = None):
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.params = params or {}

    @abc.abstractmethod
    def on_trade(self, trade: Trade) -> Signal | None:
        """Process a trade tick. Return a Signal if the strategy wants to act."""
        ...

    @abc.abstractmethod
    def on_book_update(self, update: DepthUpdate) -> Signal | None:
        """Process an order book update. Return a Signal if the strategy wants to act."""
        ...

    def on_signal_fill(self, signal_id: str, fill_price: float) -> None:  # noqa: B027
        """Callback when a signal results in a fill. Used for strategy state updates."""


class StrategyRegistry:
    """Manages active strategies and routes events to them."""

    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.strategy_id] = strategy
        logger.info("Registered strategy: %s for %s", strategy.strategy_id, strategy.symbol)

    def unregister(self, strategy_id: str) -> None:
        self._strategies.pop(strategy_id, None)

    def get(self, strategy_id: str) -> BaseStrategy | None:
        return self._strategies.get(strategy_id)

    @property
    def all(self) -> list[BaseStrategy]:
        return list(self._strategies.values())

    def strategies_for_symbol(self, symbol: str) -> list[BaseStrategy]:
        return [s for s in self._strategies.values() if s.symbol == symbol]
