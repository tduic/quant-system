#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "quant_cpp/order_book.h"
#include "quant_cpp/feature_engine.h"
#include "quant_cpp/matching_engine.h"

namespace py = pybind11;

PYBIND11_MODULE(quant_cpp, m) {
    m.doc() = "C++ performance-critical components for the quant trading system";

    // ── OrderBook ────────────────────────────────────────────────────────
    py::class_<quant::OrderBook>(m, "OrderBook")
        .def(py::init<std::string>(), py::arg("symbol"))
        .def("apply_delta", &quant::OrderBook::apply_delta,
             py::arg("bids"), py::arg("asks"),
             "Apply a batch of bid/ask deltas. Qty == 0 means remove level.")
        .def("best_bid", &quant::OrderBook::best_bid,
             "Highest bid: (price, quantity), or None if empty.")
        .def("best_ask", &quant::OrderBook::best_ask,
             "Lowest ask: (price, quantity), or None if empty.")
        .def("mid_price", &quant::OrderBook::mid_price,
             "Midpoint between best bid and ask, or None.")
        .def("spread", &quant::OrderBook::spread,
             "Spread (best_ask - best_bid), or None.")
        .def("imbalance", &quant::OrderBook::imbalance,
             py::arg("levels") = 5,
             "Order book imbalance across top N levels. Range: [-1, 1].")
        .def("top_bids", &quant::OrderBook::top_bids,
             py::arg("levels") = 10,
             "Top N bid levels sorted by price descending.")
        .def("top_asks", &quant::OrderBook::top_asks,
             py::arg("levels") = 10,
             "Top N ask levels sorted by price ascending.")
        .def_property_readonly("symbol", &quant::OrderBook::symbol)
        .def_property_readonly("bid_count", &quant::OrderBook::bid_count)
        .def_property_readonly("ask_count", &quant::OrderBook::ask_count);

    // ── Features (struct) ────────────────────────────────────────────────
    py::class_<quant::Features>(m, "Features")
        .def(py::init<>())
        .def_readwrite("timestamp", &quant::Features::timestamp)
        .def_readwrite("symbol", &quant::Features::symbol)
        .def_readwrite("vwap", &quant::Features::vwap)
        .def_readwrite("trade_imbalance", &quant::Features::trade_imbalance)
        .def_readwrite("volatility", &quant::Features::volatility)
        .def_readwrite("trade_rate", &quant::Features::trade_rate)
        .def_readwrite("mid_price", &quant::Features::mid_price)
        .def_readwrite("spread", &quant::Features::spread)
        .def_readwrite("book_imbalance", &quant::Features::book_imbalance);

    // ── FeatureEngine ────────────────────────────────────────────────────
    py::class_<quant::FeatureEngine>(m, "FeatureEngine")
        .def(py::init<std::string, int>(),
             py::arg("symbol"), py::arg("window_size") = 100)
        .def("on_trade", &quant::FeatureEngine::on_trade,
             py::arg("price"), py::arg("quantity"),
             py::arg("is_buyer_maker"), py::arg("timestamp_ms"),
             "Ingest a new trade tick.")
        .def("on_book_snapshot", &quant::FeatureEngine::on_book_snapshot,
             py::arg("mid_price"), py::arg("spread"), py::arg("imbalance"),
             "Update latest book state.")
        .def("compute", &quant::FeatureEngine::compute,
             "Compute current feature snapshot.")
        .def_property_readonly("symbol", &quant::FeatureEngine::symbol)
        .def_property_readonly("count", &quant::FeatureEngine::count);

    // ── FillResult (struct) ──────────────────────────────────────────────
    py::class_<quant::FillResult>(m, "FillResult")
        .def(py::init<>())
        .def_readwrite("fill_price", &quant::FillResult::fill_price)
        .def_readwrite("slippage_bps", &quant::FillResult::slippage_bps)
        .def_readwrite("fee", &quant::FillResult::fee)
        .def_readwrite("market_impact", &quant::FillResult::market_impact);

    // ── MatchingEngine ───────────────────────────────────────────────────
    py::class_<quant::MatchingEngine>(m, "MatchingEngine")
        .def(py::init<double, double, bool, uint64_t>(),
             py::arg("fee_rate") = 0.006,
             py::arg("latency_ms") = 50.0,
             py::arg("use_brownian_bridge") = false,
             py::arg("seed") = 42)
        .def("set_volatility", &quant::MatchingEngine::set_volatility,
             py::arg("volatility"),
             "Update the current volatility estimate.")
        .def("simulate_fill", &quant::MatchingEngine::simulate_fill,
             py::arg("side"), py::arg("quantity"),
             py::arg("mid_price"), py::arg("spread"),
             py::arg("book_depth") = std::vector<std::pair<double, double>>{},
             "Simulate a market order fill.")
        .def_static("walk_the_book", &quant::MatchingEngine::walk_the_book,
             py::arg("quantity"), py::arg("book_depth"),
             "Walk the order book to compute VWAP fill price.")
        .def("brownian_bridge_sample", &quant::MatchingEngine::brownian_bridge_sample,
             py::arg("start_price"), py::arg("end_price"),
             py::arg("volatility"), py::arg("dt_seconds"),
             "Sample from a Brownian bridge between two endpoints.")
        .def_property_readonly("fee_rate", &quant::MatchingEngine::fee_rate)
        .def_property_readonly("latency_ms", &quant::MatchingEngine::latency_ms);
}
