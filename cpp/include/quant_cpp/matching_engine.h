#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace quant {

/**
 * Result of a simulated fill.
 */
struct FillResult {
    double fill_price = 0.0;
    double slippage_bps = 0.0;
    double fee = 0.0;
    double market_impact = 0.0;  // price impact from walking the book
};

/**
 * Matching engine simulator for realistic backtesting.
 *
 * Combines three fill models:
 *   1. Walk-the-book: compute average fill price by consuming liquidity levels
 *   2. Brownian bridge: model price movement during order latency
 *   3. Simple spread: mid ± half spread (fallback)
 *
 * In Phase 6, this replaces the Python FillSimulator for performance-critical
 * backtesting where millions of fills need to be computed.
 */
class MatchingEngine {
public:
    explicit MatchingEngine(
        double fee_rate = 0.006,
        double latency_ms = 50.0,
        bool use_brownian_bridge = false,
        uint64_t seed = 42
    );

    /// Update the current volatility estimate.
    void set_volatility(double volatility);

    /// Simulate a market order fill.
    /// side: "BUY" or "SELL"
    /// book_depth: levels as (price, size) pairs. For buys: ascending asks.
    FillResult simulate_fill(
        const std::string& side,
        double quantity,
        double mid_price,
        double spread,
        const std::vector<std::pair<double, double>>& book_depth = {}
    );

    /// Walk the order book to compute volume-weighted average fill price.
    static double walk_the_book(
        double quantity,
        const std::vector<std::pair<double, double>>& book_depth
    );

    /// Sample from a Brownian bridge between two endpoints.
    double brownian_bridge_sample(
        double start_price,
        double end_price,
        double volatility,
        double dt_seconds
    );

    double fee_rate() const { return fee_rate_; }
    double latency_ms() const { return latency_ms_; }

private:
    double fee_rate_;
    double latency_ms_;
    bool use_brownian_bridge_;
    double volatility_ = 0.0;

    // Simple xorshift64 PRNG for reproducible fills
    uint64_t rng_state_;
    double next_gaussian();
    uint64_t next_u64();
};

}  // namespace quant
