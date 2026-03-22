#include "quant_cpp/matching_engine.h"
#include "test_helpers.h"

using quant::MatchingEngine;
using quant::FillResult;

void test_simple_buy_fill() {
    MatchingEngine engine(0.006, 50.0, false);
    auto result = engine.simulate_fill("BUY", 1.0, 100.0, 2.0);
    // BUY at mid + half_spread = 100 + 1 = 101
    ASSERT_NEAR(result.fill_price, 101.0, 1e-9);
    ASSERT_NEAR(result.fee, 1.0 * 101.0 * 0.006, 1e-9);
}

void test_simple_sell_fill() {
    MatchingEngine engine(0.006, 50.0, false);
    auto result = engine.simulate_fill("SELL", 1.0, 100.0, 2.0);
    // SELL at mid - half_spread = 100 - 1 = 99
    ASSERT_NEAR(result.fill_price, 99.0, 1e-9);
}

void test_slippage_bps() {
    MatchingEngine engine(0.006, 50.0, false);
    auto result = engine.simulate_fill("BUY", 1.0, 100.0, 2.0);
    // slippage = |101 - 100| / 100 * 10000 = 100 bps
    ASSERT_NEAR(result.slippage_bps, 100.0, 1e-9);
}

void test_walk_the_book_single_level() {
    std::vector<std::pair<double, double>> depth = {{101.0, 5.0}};
    double price = MatchingEngine::walk_the_book(1.0, depth);
    ASSERT_NEAR(price, 101.0, 1e-9);
}

void test_walk_the_book_multiple_levels() {
    // Buy 3 units: 2 at 101, 1 at 102
    std::vector<std::pair<double, double>> depth = {{101.0, 2.0}, {102.0, 5.0}};
    double price = MatchingEngine::walk_the_book(3.0, depth);
    // VWAP = (2*101 + 1*102) / 3 = 304/3 = 101.333...
    ASSERT_NEAR(price, 304.0 / 3.0, 1e-9);
}

void test_walk_the_book_exceeds_depth() {
    // Only 3 available but want 5
    std::vector<std::pair<double, double>> depth = {{101.0, 2.0}, {102.0, 1.0}};
    double price = MatchingEngine::walk_the_book(5.0, depth);
    // Fills 3 out of 5: VWAP = (2*101 + 1*102) / 3
    ASSERT_NEAR(price, 304.0 / 3.0, 1e-9);
}

void test_walk_the_book_empty() {
    std::vector<std::pair<double, double>> depth = {};
    double price = MatchingEngine::walk_the_book(1.0, depth);
    ASSERT_NEAR(price, 0.0, 1e-9);
}

void test_fill_with_book_depth() {
    MatchingEngine engine(0.006, 50.0, false);
    std::vector<std::pair<double, double>> depth = {{101.0, 2.0}, {102.0, 5.0}};
    auto result = engine.simulate_fill("BUY", 3.0, 100.0, 2.0, depth);
    // With book depth and no brownian bridge, uses walk_the_book
    ASSERT_NEAR(result.fill_price, 304.0 / 3.0, 1e-9);
}

void test_brownian_bridge_deterministic() {
    // With seed=42, results should be reproducible
    MatchingEngine engine1(0.006, 50.0, true, 42);
    engine1.set_volatility(0.5);
    auto r1 = engine1.simulate_fill("BUY", 1.0, 100.0, 2.0);

    MatchingEngine engine2(0.006, 50.0, true, 42);
    engine2.set_volatility(0.5);
    auto r2 = engine2.simulate_fill("BUY", 1.0, 100.0, 2.0);

    ASSERT_NEAR(r1.fill_price, r2.fill_price, 1e-9);
}

void test_brownian_bridge_zero_vol_fallback() {
    MatchingEngine engine(0.006, 50.0, true, 42);
    // volatility = 0, should fall back to simple spread
    auto result = engine.simulate_fill("BUY", 1.0, 100.0, 2.0);
    ASSERT_NEAR(result.fill_price, 101.0, 1e-9);
}

void test_fee_calculation() {
    MatchingEngine engine(0.001, 50.0, false);  // 0.1% fee
    auto result = engine.simulate_fill("BUY", 2.0, 1000.0, 2.0);
    // fill_price = 1001, fee = 2 * 1001 * 0.001 = 2.002
    ASSERT_NEAR(result.fee, 2.0 * 1001.0 * 0.001, 1e-9);
}

int main() {
    std::cout << "MatchingEngine tests:\n";
    RUN_TEST(test_simple_buy_fill);
    RUN_TEST(test_simple_sell_fill);
    RUN_TEST(test_slippage_bps);
    RUN_TEST(test_walk_the_book_single_level);
    RUN_TEST(test_walk_the_book_multiple_levels);
    RUN_TEST(test_walk_the_book_exceeds_depth);
    RUN_TEST(test_walk_the_book_empty);
    RUN_TEST(test_fill_with_book_depth);
    RUN_TEST(test_brownian_bridge_deterministic);
    RUN_TEST(test_brownian_bridge_zero_vol_fallback);
    RUN_TEST(test_fee_calculation);
    TEST_SUMMARY();
}
