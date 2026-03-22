#include "quant_cpp/matching_engine.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace quant {

// Seconds in a year (crypto: 365 * 24 * 3600)
static constexpr double SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0;

MatchingEngine::MatchingEngine(double fee_rate, double latency_ms, bool use_brownian_bridge, uint64_t seed)
    : fee_rate_(fee_rate), latency_ms_(latency_ms),
      use_brownian_bridge_(use_brownian_bridge), rng_state_(seed) {}

void MatchingEngine::set_volatility(double volatility) {
    volatility_ = volatility;
}

uint64_t MatchingEngine::next_u64() {
    // xorshift64
    uint64_t x = rng_state_;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    rng_state_ = x;
    return x;
}

double MatchingEngine::next_gaussian() {
    // Box-Muller transform
    constexpr double TWO_PI = 2.0 * 3.14159265358979323846;
    double u1, u2;
    do {
        u1 = static_cast<double>(next_u64()) / static_cast<double>(UINT64_MAX);
    } while (u1 == 0.0);
    u2 = static_cast<double>(next_u64()) / static_cast<double>(UINT64_MAX);
    return std::sqrt(-2.0 * std::log(u1)) * std::cos(TWO_PI * u2);
}

double MatchingEngine::walk_the_book(
    double quantity,
    const std::vector<std::pair<double, double>>& book_depth
) {
    if (book_depth.empty()) return 0.0;

    double remaining = quantity;
    double total_cost = 0.0;

    for (const auto& [price, size] : book_depth) {
        double fill_at_level = std::min(remaining, size);
        total_cost += fill_at_level * price;
        remaining -= fill_at_level;
        if (remaining <= 0.0) break;
    }

    double filled_qty = quantity - remaining;
    if (filled_qty <= 0.0) return book_depth[0].first;

    return total_cost / filled_qty;
}

double MatchingEngine::brownian_bridge_sample(
    double start_price,
    double end_price,
    double volatility,
    double dt_seconds
) {
    if (dt_seconds <= 0.0 || volatility <= 0.0) {
        return (start_price + end_price) / 2.0;
    }

    double t = dt_seconds / 2.0;
    double total_time = dt_seconds;

    // Bridge mean at midpoint
    double bridge_mean = start_price + (end_price - start_price) * (t / total_time);

    // Bridge variance: sigma^2 * t * (T-t) / T
    double bridge_var = (volatility * volatility) * t * (total_time - t) / total_time;
    double bridge_std = std::sqrt(bridge_var);

    double z = next_gaussian();
    return bridge_mean + z * bridge_std;
}

FillResult MatchingEngine::simulate_fill(
    const std::string& side,
    double quantity,
    double mid_price,
    double spread,
    const std::vector<std::pair<double, double>>& book_depth
) {
    FillResult result;
    double fill_price;

    bool is_buy = (side == "BUY");
    double half_spread = spread / 2.0;

    if (use_brownian_bridge_ && volatility_ > 0.0) {
        // Brownian bridge fill
        double dt_seconds = latency_ms_ / 1000.0;
        double vol_per_second = volatility_ / std::sqrt(SECONDS_PER_YEAR);

        double arrival_side = is_buy ? mid_price + half_spread : mid_price - half_spread;

        double bridge_price = brownian_bridge_sample(
            mid_price, arrival_side,
            vol_per_second * mid_price,  // absolute vol
            dt_seconds
        );

        if (!book_depth.empty()) {
            double book_fill = walk_the_book(quantity, book_depth);
            result.market_impact = std::abs(book_fill - (is_buy ? book_depth[0].first : book_depth[0].first));
            fill_price = (bridge_price + book_fill) / 2.0;
        } else {
            fill_price = bridge_price;
        }
    } else if (!book_depth.empty()) {
        fill_price = walk_the_book(quantity, book_depth);
        result.market_impact = std::abs(fill_price - book_depth[0].first);
    } else {
        // Simple spread model
        fill_price = is_buy ? mid_price + half_spread : mid_price - half_spread;
    }

    result.fill_price = fill_price;
    result.slippage_bps = (mid_price > 0.0)
        ? std::abs(fill_price - mid_price) / mid_price * 10000.0
        : 0.0;
    result.fee = quantity * fill_price * fee_rate_;

    return result;
}

}  // namespace quant
