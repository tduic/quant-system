#include "quant_cpp/feature_engine.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace quant {

FeatureEngine::FeatureEngine(std::string symbol, int window_size)
    : symbol_(std::move(symbol)), window_size_(window_size) {}

void FeatureEngine::on_trade(double price, double quantity, bool is_buyer_maker, int64_t timestamp_ms) {
    // Evict oldest if at capacity
    if (static_cast<int>(prices_.size()) >= window_size_) {
        double old_p = prices_.front();
        double old_q = quantities_.front();
        pv_sum_ -= old_p * old_q;
        v_sum_ -= old_q;
        prices_.pop_front();
        quantities_.pop_front();
        sides_.pop_front();
        timestamps_.pop_front();
    }

    prices_.push_back(price);
    quantities_.push_back(quantity);
    sides_.push_back(is_buyer_maker);
    timestamps_.push_back(timestamp_ms);
    pv_sum_ += price * quantity;
    v_sum_ += quantity;
}

void FeatureEngine::on_book_snapshot(std::optional<double> mid_price, std::optional<double> spread, double imbalance) {
    mid_price_ = mid_price;
    spread_ = spread;
    book_imbalance_ = imbalance;
}

Features FeatureEngine::compute() const {
    Features f;
    f.symbol = symbol_;
    f.mid_price = mid_price_;
    f.spread = spread_;
    f.book_imbalance = book_imbalance_;

    const size_t n = prices_.size();
    if (n == 0) return f;

    f.timestamp = timestamps_.back();

    // VWAP
    f.vwap = (v_sum_ > 0.0) ? pv_sum_ / v_sum_ : 0.0;

    // Trade imbalance
    double buy_vol = 0.0, sell_vol = 0.0;
    for (size_t i = 0; i < n; ++i) {
        if (sides_[i]) {
            buy_vol += quantities_[i];
        } else {
            sell_vol += quantities_[i];
        }
    }
    double total_vol = buy_vol + sell_vol;
    f.trade_imbalance = (total_vol > 0.0) ? (buy_vol - sell_vol) / total_vol : 0.0;

    // Volatility: std of simple returns
    if (n >= 2) {
        std::vector<double> returns;
        returns.reserve(n - 1);
        for (size_t i = 1; i < n; ++i) {
            if (prices_[i - 1] > 0.0) {
                returns.push_back(prices_[i] / prices_[i - 1] - 1.0);
            }
        }
        if (!returns.empty()) {
            double mean = std::accumulate(returns.begin(), returns.end(), 0.0) / static_cast<double>(returns.size());
            double variance = 0.0;
            for (double r : returns) {
                double diff = r - mean;
                variance += diff * diff;
            }
            variance /= static_cast<double>(returns.size());
            f.volatility = std::sqrt(variance);
        }
    }

    // Trade rate (trades per second)
    if (n >= 2) {
        double time_span_s = static_cast<double>(timestamps_.back() - timestamps_.front()) / 1000.0;
        if (time_span_s > 0.0) {
            f.trade_rate = static_cast<double>(n) / time_span_s;
        }
    }

    return f;
}

}  // namespace quant
