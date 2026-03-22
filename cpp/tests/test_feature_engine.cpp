#include "quant_cpp/feature_engine.h"
#include "test_helpers.h"

using quant::FeatureEngine;

void test_empty_engine() {
    FeatureEngine engine("BTCUSD", 100);
    ASSERT_EQ(engine.symbol(), "BTCUSD");
    ASSERT_EQ(engine.count(), 0u);
    auto f = engine.compute();
    ASSERT_NEAR(f.vwap, 0.0, 1e-9);
    ASSERT_NEAR(f.volatility, 0.0, 1e-9);
}

void test_single_trade() {
    FeatureEngine engine("BTCUSD", 100);
    engine.on_trade(100.0, 1.0, false, 1000);
    ASSERT_EQ(engine.count(), 1u);
    auto f = engine.compute();
    ASSERT_NEAR(f.vwap, 100.0, 1e-9);
    ASSERT_NEAR(f.volatility, 0.0, 1e-9);  // need 2+ trades
    ASSERT_EQ(f.timestamp, 1000);
}

void test_vwap_calculation() {
    FeatureEngine engine("BTCUSD", 100);
    // VWAP = (100*1 + 200*3) / (1 + 3) = 700/4 = 175
    engine.on_trade(100.0, 1.0, false, 1000);
    engine.on_trade(200.0, 3.0, true, 2000);
    auto f = engine.compute();
    ASSERT_NEAR(f.vwap, 175.0, 1e-9);
}

void test_trade_imbalance() {
    FeatureEngine engine("BTCUSD", 100);
    // buyer_maker=true means seller-initiated (taker sells)
    // buyer_maker=false means buyer-initiated (taker buys)
    engine.on_trade(100.0, 3.0, true, 1000);   // 3 units buyer-maker
    engine.on_trade(100.0, 1.0, false, 2000);   // 1 unit not buyer-maker
    auto f = engine.compute();
    // imbalance = (buy_vol - sell_vol) / total = (3 - 1) / 4 = 0.5
    ASSERT_NEAR(f.trade_imbalance, 0.5, 1e-9);
}

void test_volatility() {
    FeatureEngine engine("BTCUSD", 100);
    engine.on_trade(100.0, 1.0, false, 1000);
    engine.on_trade(110.0, 1.0, false, 2000);  // +10% return
    engine.on_trade(100.0, 1.0, false, 3000);  // -9.09% return
    auto f = engine.compute();
    ASSERT_TRUE(f.volatility > 0.0);
}

void test_trade_rate() {
    FeatureEngine engine("BTCUSD", 100);
    // 5 trades over 4 seconds
    for (int i = 0; i < 5; ++i) {
        engine.on_trade(100.0, 1.0, false, i * 1000);
    }
    auto f = engine.compute();
    // rate = 5 trades / 4 seconds = 1.25
    ASSERT_NEAR(f.trade_rate, 1.25, 1e-9);
}

void test_window_eviction() {
    FeatureEngine engine("BTCUSD", 3);
    engine.on_trade(100.0, 1.0, false, 1000);
    engine.on_trade(200.0, 1.0, false, 2000);
    engine.on_trade(300.0, 1.0, false, 3000);
    ASSERT_EQ(engine.count(), 3u);

    // This should evict the first trade (100.0)
    engine.on_trade(400.0, 1.0, false, 4000);
    ASSERT_EQ(engine.count(), 3u);

    auto f = engine.compute();
    // VWAP = (200 + 300 + 400) / 3 = 300
    ASSERT_NEAR(f.vwap, 300.0, 1e-9);
}

void test_book_snapshot() {
    FeatureEngine engine("BTCUSD", 100);
    engine.on_trade(100.0, 1.0, false, 1000);
    engine.on_book_snapshot(100.5, 1.0, 0.3);
    auto f = engine.compute();
    ASSERT_TRUE(f.mid_price.has_value());
    ASSERT_NEAR(*f.mid_price, 100.5, 1e-9);
    ASSERT_TRUE(f.spread.has_value());
    ASSERT_NEAR(*f.spread, 1.0, 1e-9);
    ASSERT_NEAR(f.book_imbalance, 0.3, 1e-9);
}

int main() {
    std::cout << "FeatureEngine tests:\n";
    RUN_TEST(test_empty_engine);
    RUN_TEST(test_single_trade);
    RUN_TEST(test_vwap_calculation);
    RUN_TEST(test_trade_imbalance);
    RUN_TEST(test_volatility);
    RUN_TEST(test_trade_rate);
    RUN_TEST(test_window_eviction);
    RUN_TEST(test_book_snapshot);
    TEST_SUMMARY();
}
