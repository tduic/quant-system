#include "quant_cpp/order_book.h"
#include "test_helpers.h"

using quant::OrderBook;

void test_empty_book() {
    OrderBook book("BTCUSD");
    ASSERT_EQ(book.symbol(), "BTCUSD");
    ASSERT_FALSE(book.best_bid().has_value());
    ASSERT_FALSE(book.best_ask().has_value());
    ASSERT_FALSE(book.mid_price().has_value());
    ASSERT_FALSE(book.spread().has_value());
    ASSERT_NEAR(book.imbalance(), 0.0, 1e-9);
}

void test_apply_delta_bids() {
    OrderBook book("BTCUSD");
    book.apply_delta({{100.0, 1.0}, {99.0, 2.0}}, {});
    auto bid = book.best_bid();
    ASSERT_TRUE(bid.has_value());
    ASSERT_NEAR(bid->first, 100.0, 1e-9);
    ASSERT_NEAR(bid->second, 1.0, 1e-9);
    ASSERT_EQ(book.bid_count(), 2u);
}

void test_apply_delta_asks() {
    OrderBook book("BTCUSD");
    book.apply_delta({}, {{101.0, 1.5}, {102.0, 3.0}});
    auto ask = book.best_ask();
    ASSERT_TRUE(ask.has_value());
    ASSERT_NEAR(ask->first, 101.0, 1e-9);
    ASSERT_NEAR(ask->second, 1.5, 1e-9);
    ASSERT_EQ(book.ask_count(), 2u);
}

void test_mid_price_and_spread() {
    OrderBook book("BTCUSD");
    book.apply_delta({{100.0, 1.0}}, {{102.0, 1.0}});
    ASSERT_TRUE(book.mid_price().has_value());
    ASSERT_NEAR(*book.mid_price(), 101.0, 1e-9);
    ASSERT_TRUE(book.spread().has_value());
    ASSERT_NEAR(*book.spread(), 2.0, 1e-9);
}

void test_remove_level() {
    OrderBook book("BTCUSD");
    book.apply_delta({{100.0, 1.0}, {99.0, 2.0}}, {});
    ASSERT_EQ(book.bid_count(), 2u);

    // Remove the top bid
    book.apply_delta({{100.0, 0.0}}, {});
    ASSERT_EQ(book.bid_count(), 1u);
    auto bid = book.best_bid();
    ASSERT_NEAR(bid->first, 99.0, 1e-9);
}

void test_update_level() {
    OrderBook book("BTCUSD");
    book.apply_delta({{100.0, 1.0}}, {});
    book.apply_delta({{100.0, 5.0}}, {});  // update quantity
    ASSERT_EQ(book.bid_count(), 1u);
    ASSERT_NEAR(book.best_bid()->second, 5.0, 1e-9);
}

void test_imbalance() {
    OrderBook book("BTCUSD");
    // 3 units on bid side, 1 unit on ask side
    book.apply_delta({{100.0, 3.0}}, {{101.0, 1.0}});
    // imbalance = (3 - 1) / (3 + 1) = 0.5
    ASSERT_NEAR(book.imbalance(), 0.5, 1e-9);
}

void test_top_bids_sorted() {
    OrderBook book("BTCUSD");
    book.apply_delta({{98.0, 1.0}, {100.0, 2.0}, {99.0, 3.0}}, {});
    auto bids = book.top_bids(2);
    ASSERT_EQ(bids.size(), 2u);
    ASSERT_NEAR(bids[0].first, 100.0, 1e-9);  // highest first
    ASSERT_NEAR(bids[1].first, 99.0, 1e-9);
}

void test_top_asks_sorted() {
    OrderBook book("BTCUSD");
    book.apply_delta({}, {{103.0, 1.0}, {101.0, 2.0}, {102.0, 3.0}});
    auto asks = book.top_asks(2);
    ASSERT_EQ(asks.size(), 2u);
    ASSERT_NEAR(asks[0].first, 101.0, 1e-9);  // lowest first
    ASSERT_NEAR(asks[1].first, 102.0, 1e-9);
}

int main() {
    std::cout << "OrderBook tests:\n";
    RUN_TEST(test_empty_book);
    RUN_TEST(test_apply_delta_bids);
    RUN_TEST(test_apply_delta_asks);
    RUN_TEST(test_mid_price_and_spread);
    RUN_TEST(test_remove_level);
    RUN_TEST(test_update_level);
    RUN_TEST(test_imbalance);
    RUN_TEST(test_top_bids_sorted);
    RUN_TEST(test_top_asks_sorted);
    TEST_SUMMARY();
}
