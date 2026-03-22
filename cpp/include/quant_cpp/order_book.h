#pragma once

#include <map>
#include <optional>
#include <utility>
#include <vector>
#include <string>

namespace quant {

/**
 * L2 order book maintained from incremental depth updates.
 *
 * Uses std::map for automatic price-level sorting:
 *   - bids: reverse-sorted (highest first)
 *   - asks: forward-sorted (lowest first)
 *
 * This gives O(log n) insert/delete and O(1) best bid/ask.
 */
class OrderBook {
public:
    explicit OrderBook(std::string symbol);

    /// Apply a batch of bid/ask deltas. Qty == 0 means remove level.
    void apply_delta(
        const std::vector<std::pair<double, double>>& bids,
        const std::vector<std::pair<double, double>>& asks
    );

    /// Highest bid: (price, quantity), or nullopt if empty.
    std::optional<std::pair<double, double>> best_bid() const;

    /// Lowest ask: (price, quantity), or nullopt if empty.
    std::optional<std::pair<double, double>> best_ask() const;

    /// Midpoint between best bid and ask, or nullopt.
    std::optional<double> mid_price() const;

    /// Spread (best_ask - best_bid), or nullopt.
    std::optional<double> spread() const;

    /// Order book imbalance across top N levels. Range: [-1, 1].
    double imbalance(int levels = 5) const;

    /// Top N bid levels sorted by price descending.
    std::vector<std::pair<double, double>> top_bids(int levels = 10) const;

    /// Top N ask levels sorted by price ascending.
    std::vector<std::pair<double, double>> top_asks(int levels = 10) const;

    const std::string& symbol() const { return symbol_; }
    size_t bid_count() const { return bids_.size(); }
    size_t ask_count() const { return asks_.size(); }

private:
    std::string symbol_;
    std::map<double, double, std::greater<>> bids_;  // price desc
    std::map<double, double> asks_;                    // price asc
};

}  // namespace quant
