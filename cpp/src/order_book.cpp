#include "quant_cpp/order_book.h"

#include <algorithm>
#include <cmath>

namespace quant {

OrderBook::OrderBook(std::string symbol) : symbol_(std::move(symbol)) {}

void OrderBook::apply_delta(
    const std::vector<std::pair<double, double>>& bids,
    const std::vector<std::pair<double, double>>& asks
) {
    for (const auto& [price, qty] : bids) {
        if (qty == 0.0) {
            bids_.erase(price);
        } else {
            bids_[price] = qty;
        }
    }
    for (const auto& [price, qty] : asks) {
        if (qty == 0.0) {
            asks_.erase(price);
        } else {
            asks_[price] = qty;
        }
    }
}

std::optional<std::pair<double, double>> OrderBook::best_bid() const {
    if (bids_.empty()) return std::nullopt;
    const auto& [price, qty] = *bids_.begin();  // greatest key (std::greater)
    return std::make_pair(price, qty);
}

std::optional<std::pair<double, double>> OrderBook::best_ask() const {
    if (asks_.empty()) return std::nullopt;
    const auto& [price, qty] = *asks_.begin();  // smallest key
    return std::make_pair(price, qty);
}

std::optional<double> OrderBook::mid_price() const {
    auto bid = best_bid();
    auto ask = best_ask();
    if (!bid || !ask) return std::nullopt;
    return (bid->first + ask->first) / 2.0;
}

std::optional<double> OrderBook::spread() const {
    auto bid = best_bid();
    auto ask = best_ask();
    if (!bid || !ask) return std::nullopt;
    return ask->first - bid->first;
}

double OrderBook::imbalance(int levels) const {
    double bid_volume = 0.0;
    double ask_volume = 0.0;

    int count = 0;
    for (const auto& [price, qty] : bids_) {
        bid_volume += qty;
        if (++count >= levels) break;
    }

    count = 0;
    for (const auto& [price, qty] : asks_) {
        ask_volume += qty;
        if (++count >= levels) break;
    }

    double total = bid_volume + ask_volume;
    if (total == 0.0) return 0.0;
    return (bid_volume - ask_volume) / total;
}

std::vector<std::pair<double, double>> OrderBook::top_bids(int levels) const {
    std::vector<std::pair<double, double>> result;
    result.reserve(std::min(static_cast<size_t>(levels), bids_.size()));
    int count = 0;
    for (const auto& [price, qty] : bids_) {
        result.emplace_back(price, qty);
        if (++count >= levels) break;
    }
    return result;
}

std::vector<std::pair<double, double>> OrderBook::top_asks(int levels) const {
    std::vector<std::pair<double, double>> result;
    result.reserve(std::min(static_cast<size_t>(levels), asks_.size()));
    int count = 0;
    for (const auto& [price, qty] : asks_) {
        result.emplace_back(price, qty);
        if (++count >= levels) break;
    }
    return result;
}

}  // namespace quant
