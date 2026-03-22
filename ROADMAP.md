# Roadmap

## Completed

### Phase 1 — Data Pipeline Foundation (Weeks 1-2)
- [x] Coinbase WebSocket market data ingestion (trades + L2 depth)
- [x] Kafka producer with LZ4 compression and backtest_id header injection
- [x] Storage service with batched COPY writes to TimescaleDB
- [x] TimescaleDB schema: hypertables, 3-tier OHLCV continuous aggregates (1m, 1h, 1d)
- [x] Compression policies (7 days) and retention policies (90 days raw, 365 days fills)
- [x] Docker Compose orchestration (Kafka, Zookeeper, TimescaleDB, Redis)
- [x] Shared library: models, Kafka/Redis helpers, config, structured logging
- [x] GitHub Actions CI (tests + Docker build)

### Phase 2 — Alpha Engine, Risk Gateway, Execution (Weeks 3-4)
- [x] Alpha Engine: Kafka consumer, order book, feature engine, strategy registry
- [x] Mean-reversion strategy (VWAP z-score with warmup, cooldown, duplicate suppression)
- [x] Risk Gateway: composable check pipeline (position size, order notional, drawdown)
- [x] Execution Service: paper trading fill simulator (spread-based slippage + fees)
- [x] End-to-end pipeline: market data → signals → risk → fills

### Phase 3 — Quantitative Methods (Weeks 5-6)
- [x] Linear regression fair value strategy (rolling OLS, 4 features, hand-rolled solver)
- [x] Parametric VaR (GBM-based, configurable confidence/horizon, plugged into risk checks)
- [x] Brownian bridge slippage model (price movement during order latency)
- [x] Walk-the-book market impact model
- [x] Ruff linting and formatting (integrated into CI)

## Up Next

### Phase 4 — Post-Trade Dashboard (Weeks 7-8)
Core logic is implemented and tested. Remaining work:
- [ ] Wire up post-trade Kafka consumer (ingest fills + market data)
- [ ] Real-time PnL computation (realized + unrealized, per symbol, per strategy)
- [ ] FastAPI dashboard with 6 tabs:
  - PnL attribution
  - Transaction cost analysis (slippage decomposition)
  - Alpha decay curves (IC at various horizons)
  - Risk metrics (Sharpe, Sortino, Calmar)
  - Drawdown analysis (max drawdown, duration, recovery)
  - Fill rate and order lifecycle
- [ ] Excel export endpoint (one workbook, separate sheets per tab)
- [ ] Uncomment post-trade service in docker-compose

### Phase 5 — Backtesting (Weeks 9-10)
- [ ] Backtest Replay Service: reads historical ticks from TimescaleDB, injects into Kafka
- [ ] `backtest_id` header on every message — all downstream services namespace state by ID
- [ ] Same code runs in both live and backtest modes (no `if backtest:` branches)
- [ ] Redis state isolation per backtest run
- [ ] Database writes tagged with backtest_id for separate analysis
- [ ] CLI to launch/monitor/compare backtest runs

### Phase 6 — C++ Performance (Weeks 11-14)
- [ ] pybind11 build infrastructure (CMake, shared library compilation)
- [ ] C++ OrderBook: L2 book with price-level map, O(1) best bid/ask
- [ ] C++ FeatureEngine: rolling statistics with online algorithms
- [ ] C++ MatchingEngine: realistic fill simulation with queue priority
- [ ] Python interface preserved — swap `.so` imports, no service code changes
- [ ] Benchmark suite comparing Python vs C++ throughput

### Phase 7 — Dashboard Frontend (Weeks 15-16)
- [ ] TypeScript React frontend (`services/post-trade/frontend/`)
- [ ] 6 tabs matching the FastAPI endpoints
- [ ] Real-time updates via WebSocket from FastAPI
- [ ] Charts with recharts/d3
- [ ] Excel download button
- [ ] Responsive layout

## Design Decisions

**Microservice over monolith**: Each service is a separate Docker container communicating via Kafka. More complex to operate but isolates failures, enables independent scaling, and — critically — means the backtesting replay service can feed historical data through the same pipeline without any code changes.

**TimescaleDB over QuestDB/InfluxDB**: TimescaleDB is PostgreSQL underneath, so orders, fills, and metadata tables live in the same database and can JOIN with tick data using normal SQL. Purpose-built TSDBs would require a separate relational database.

**No numpy in the hot path**: The linear regression solver uses hand-rolled Gaussian elimination. numpy would be faster for large matrices but adds a heavy dependency and import time to the Alpha Engine. The C++ migration in Phase 6 will handle performance.

**Coinbase over Binance**: Binance's global API returns HTTP 451 for US IPs. Binance.US has very low volume. Coinbase is fully US-legal, no auth needed for public market data, and has good BTC-USD liquidity.

**Python 3.14**: Targets the latest stable release. The GIL is still present (free-threading not enabled), so parallelism comes from the microservice architecture (process-level) and asyncio (I/O-level). CPU-bound wins come from the C++ migration.
