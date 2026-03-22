#pragma once

#include <cstdint>
#include <deque>
#include <optional>
#include <string>

namespace quant {

/**
 * Snapshot of computed features at a point in time.
 */
struct Features {
    int64_t timestamp = 0;
    std::string symbol;
    double vwap = 0.0;
    double trade_imbalance = 0.0;
    double volatility = 0.0;
    double trade_rate = 0.0;
    std::optional<double> mid_price;
    std::optional<double> spread;
    double book_imbalance = 0.0;
};

/**
 * Rolling feature computation engine.
 *
 * Computes real-time features from the tick stream using a fixed-size
 * sliding window. Maintains running sums for O(1) VWAP updates.
 */
class FeatureEngine {
public:
    explicit FeatureEngine(std::string symbol, int window_size = 100);

    /// Ingest a new trade tick.
    void on_trade(double price, double quantity, bool is_buyer_maker, int64_t timestamp_ms);

    /// Update latest book state.
    void on_book_snapshot(std::optional<double> mid_price, std::optional<double> spread, double imbalance);

    /// Compute current feature snapshot.
    Features compute() const;

    const std::string& symbol() const { return symbol_; }
    size_t count() const { return prices_.size(); }

private:
    std::string symbol_;
    int window_size_;

    std::deque<double> prices_;
    std::deque<double> quantities_;
    std::deque<bool> sides_;        // true = buyer maker
    std::deque<int64_t> timestamps_;

    double pv_sum_ = 0.0;   // price * volume running sum
    double v_sum_ = 0.0;    // volume running sum

    // Latest book state
    std::optional<double> mid_price_;
    std::optional<double> spread_;
    double book_imbalance_ = 0.0;
};

}  // namespace quant
