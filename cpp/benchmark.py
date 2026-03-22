"""Benchmark: C++ vs Python implementations.

Measures throughput for OrderBook, FeatureEngine, and MatchingEngine
to quantify the speedup from the C++ migration.

Usage:
    python cpp/benchmark.py
"""

from __future__ import annotations

import random
import sys
import time


def benchmark_order_book(n_updates: int = 100_000):
    """Benchmark OrderBook.apply_delta throughput."""
    print(f"\n{'='*60}")
    print(f"OrderBook benchmark: {n_updates:,} updates")
    print(f"{'='*60}")

    # Generate random deltas
    random.seed(42)
    deltas = []
    for _ in range(n_updates):
        bids = [(random.uniform(99, 100), random.uniform(0, 10)) for _ in range(5)]
        asks = [(random.uniform(100, 101), random.uniform(0, 10)) for _ in range(5)]
        deltas.append((bids, asks))

    # Python
    from alpha_engine_svc.order_book import OrderBook as PyBook

    py_book = PyBook("BTCUSD")
    start = time.perf_counter()
    for bids, asks in deltas:

        class FakeDelta:
            pass

        d = FakeDelta()
        d.bids = bids
        d.asks = asks
        py_book.apply_delta(d)
    py_time = time.perf_counter() - start
    print(f"  Python:  {py_time:.3f}s  ({n_updates/py_time:,.0f} updates/s)")

    # C++
    try:
        from quant_cpp import OrderBook as CppBook

        cpp_book = CppBook("BTCUSD")
        start = time.perf_counter()
        for bids, asks in deltas:
            cpp_book.apply_delta(bids, asks)
        cpp_time = time.perf_counter() - start
        print(f"  C++:     {cpp_time:.3f}s  ({n_updates/cpp_time:,.0f} updates/s)")
        print(f"  Speedup: {py_time/cpp_time:.1f}x")
    except ImportError:
        print("  C++:     not built (run: pip install ./cpp/)")


def benchmark_feature_engine(n_trades: int = 1_000_000):
    """Benchmark FeatureEngine.on_trade + compute throughput."""
    print(f"\n{'='*60}")
    print(f"FeatureEngine benchmark: {n_trades:,} trades")
    print(f"{'='*60}")

    random.seed(42)
    trades = [
        (random.uniform(99, 101), random.uniform(0.001, 1.0), random.choice([True, False]), 1000 + i)
        for i in range(n_trades)
    ]

    # Python
    from alpha_engine_svc.feature_engine import FeatureEngine as PyEngine

    py_eng = PyEngine("BTCUSD", 100)
    start = time.perf_counter()
    for p, q, s, t in trades:
        py_eng.on_trade(p, q, s, t)
    py_eng.compute()
    py_time = time.perf_counter() - start
    print(f"  Python:  {py_time:.3f}s  ({n_trades/py_time:,.0f} trades/s)")

    # C++
    try:
        from quant_cpp import FeatureEngine as CppEngine

        cpp_eng = CppEngine("BTCUSD", 100)
        start = time.perf_counter()
        for p, q, s, t in trades:
            cpp_eng.on_trade(p, q, s, t)
        cpp_eng.compute()
        cpp_time = time.perf_counter() - start
        print(f"  C++:     {cpp_time:.3f}s  ({n_trades/cpp_time:,.0f} trades/s)")
        print(f"  Speedup: {py_time/cpp_time:.1f}x")
    except ImportError:
        print("  C++:     not built (run: pip install ./cpp/)")


def benchmark_matching_engine(n_fills: int = 100_000):
    """Benchmark MatchingEngine.simulate_fill throughput."""
    print(f"\n{'='*60}")
    print(f"MatchingEngine benchmark: {n_fills:,} fills")
    print(f"{'='*60}")

    random.seed(42)
    orders = [
        (random.choice(["BUY", "SELL"]), random.uniform(0.001, 1.0), 100.0, 0.5)
        for _ in range(n_fills)
    ]

    # C++ only (no Python MatchingEngine with same interface)
    try:
        from quant_cpp import MatchingEngine

        engine = MatchingEngine(0.006, 50.0, True, 42)
        engine.set_volatility(0.5)

        start = time.perf_counter()
        for side, qty, mid, spread in orders:
            engine.simulate_fill(side, qty, mid, spread)
        cpp_time = time.perf_counter() - start
        print(f"  C++:     {cpp_time:.3f}s  ({n_fills/cpp_time:,.0f} fills/s)")
    except ImportError:
        print("  C++:     not built (run: pip install ./cpp/)")


if __name__ == "__main__":
    # Add service paths for Python imports
    sys.path.insert(0, "services/alpha-engine")
    sys.path.insert(0, "lib")

    benchmark_order_book()
    benchmark_feature_engine()
    benchmark_matching_engine()

    print(f"\n{'='*60}")
    print("Done.")
