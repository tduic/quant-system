"""Transparent C++/Python import switching.

Attempts to import the C++ pybind11 module (quant_cpp). If not available,
falls back to the pure Python implementations. All downstream code imports
from this module and doesn't need to know which backend is active.

Usage:
    from quant_core.accelerated import OrderBook, FeatureEngine, MatchingEngine
    print(f"Using backend: {BACKEND}")
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from quant_cpp import (  # type: ignore[import-not-found]
        FeatureEngine as CppFeatureEngine,
    )
    from quant_cpp import (
        Features as CppFeatures,
    )
    from quant_cpp import (
        MatchingEngine as CppMatchingEngine,
    )
    from quant_cpp import (
        OrderBook as CppOrderBook,
    )

    OrderBook = CppOrderBook
    FeatureEngine = CppFeatureEngine
    Features = CppFeatures
    MatchingEngine = CppMatchingEngine
    BACKEND = "cpp"
    logger.info("Using C++ accelerated backend (quant_cpp)")

except ImportError:
    from alpha_engine_svc.feature_engine import FeatureEngine as PyFeatureEngine
    from alpha_engine_svc.feature_engine import Features as PyFeatures
    from alpha_engine_svc.order_book import OrderBook as PyOrderBook

    OrderBook = PyOrderBook  # type: ignore[assignment,misc]
    FeatureEngine = PyFeatureEngine  # type: ignore[assignment,misc]
    Features = PyFeatures  # type: ignore[assignment,misc]
    MatchingEngine = None  # type: ignore[assignment]
    BACKEND = "python"
    logger.info("C++ module not available, using pure Python backend")

__all__ = ["BACKEND", "FeatureEngine", "Features", "MatchingEngine", "OrderBook"]
