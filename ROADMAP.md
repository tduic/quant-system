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

### Phase 4 — Post-Trade Dashboard (Weeks 7-8)
- [x] Thread-safe in-memory state store (fills, equity curve, TCA, running metrics)
- [x] Kafka consumer for fills + raw trades (live price updates for unrealized PnL)
- [x] FastAPI dashboard with 6 tabs:
  - [x] PnL attribution (per symbol, realized + unrealized)
  - [x] Transaction cost analysis (spread, slippage, market impact, fee decomposition)
  - [ ] Alpha decay curves (placeholder — requires Phase 5 backtesting for IC tracking)
  - [x] Risk metrics (Sharpe, Sortino, Calmar, drawdown, win rate, profit factor)
  - [x] Drawdown analysis (equity curve + running drawdown)
  - [x] Fill rate and order lifecycle
- [x] Excel export endpoint (formatted .xlsx with 5 sheets, styled headers)
- [x] Post-trade service enabled in docker-compose (port 8080)

### Phase 5 — Backtesting (Weeks 9-10)
- [x] Replay engine: reads historical ticks from TimescaleDB, publishes to Kafka with backtest_id
- [x] `backtest_id` header auto-injected on every message via QProducer
- [x] Same code runs in both live and backtest modes (no `if backtest:` branches)
- [x] Three replay speed modes: as_fast_as_possible, real_time, scaled (Nx)
- [x] CLI: `backtest run`, `backtest list`, `backtest results`
- [x] File-based result storage with JSON metadata
- [x] Redis state isolation per backtest run (key schema namespaced by run_id)
- [x] Database writes tagged with backtest_id for separate analysis

### Phase 6 — C++ Performance (Weeks 11-14)
- [x] pybind11 build infrastructure (CMake + setup.py, fetches pybind11 automatically)
- [x] C++ OrderBook: L2 book with `std::map` (reverse-sorted bids, forward-sorted asks), O(log n) insert, O(1) best bid/ask
- [x] C++ FeatureEngine: rolling VWAP, volatility, trade imbalance, trade rate with online sum tracking
- [x] C++ MatchingEngine: walk-the-book + Brownian bridge + simple spread models, deterministic PRNG (xorshift64)
- [x] Full pybind11 bindings preserving Python interface — swap imports, no service code changes
- [x] Transparent import switching (`quant_core.accelerated`): tries C++ first, falls back to Python
- [x] Benchmark suite comparing Python vs C++ throughput
- [x] Native C++ test suite (28 assertions across 3 test executables)
- [x] Python test suite for C++ module (24 tests, skipped if not built)
- [x] CI job: builds C++, runs native tests, installs module, runs Python tests

### Phase 7 — Dashboard Frontend (Weeks 15-16)
- [x] TypeScript React 19 frontend (`services/post-trade/frontend/`)
- [x] Vite build tooling with Tailwind CSS
- [x] 6 tabs matching the FastAPI endpoints (P&L, TCA, Alpha Decay, Risk Metrics, Drawdown, Fills)
- [x] Auto-refreshing data via polling (5-second interval)
- [x] Equity curve and drawdown charts with recharts
- [x] Excel download button in header
- [x] Responsive grid layout with dark theme
- [x] Shared components (Card, LoadingSpinner) and typed API client
- [x] CORS middleware on FastAPI for development
- [x] Dockerfile (multi-stage: node build → nginx serve) with API reverse proxy
- [x] Docker Compose service (port 3000)
- [x] Makefile commands (fe-install, fe-dev, fe-build, fe-lint)
- [x] CI job: npm ci, tsc --noEmit, npm run build

## Up Next

### Phase 8 — Alpha Decay Implementation
- [ ] Add signal-level IC (information coefficient) tracking to the alpha engine
- [ ] Log predicted vs actual return at multiple horizons (1m, 5m, 15m, 1h) per signal
- [ ] Compute rolling IC and IC decay curves in the post-trade service
- [ ] Wire alpha decay data into the existing dashboard tab (replace placeholder)
- [ ] Backtest integration: alpha decay analysis per backtest run

### Phase 9 — Multi-Symbol Support
- [ ] Extend market data service to subscribe to multiple symbols concurrently (ETH-USD, SOL-USD, etc.)
- [ ] Per-symbol Kafka partitioning and storage pipelines
- [ ] Cross-asset feature engine inputs (correlation, relative strength)
- [ ] Portfolio-level position tracking and risk aggregation
- [ ] Pairs trading signal infrastructure
- [ ] Dashboard updates: symbol selector/filter across all tabs

### Phase 10 — Backtest Improvements
- [ ] Walk-forward optimization (rolling train/test windows)
- [ ] Parameter sensitivity analysis (grid/random search over strategy params)
- [ ] Monte Carlo simulation of trade sequences for confidence intervals on Sharpe/drawdown
- [ ] Backtest comparison view: side-by-side metrics for multiple runs
- [ ] Slippage/fee sensitivity sweeps
- [ ] Out-of-sample validation reporting

### Phase 11 — More Strategies
- [ ] Momentum/trend-following strategy (breakout or moving-average crossover)
- [ ] Order flow imbalance strategy (trade-level buy/sell pressure)
- [ ] Strategy combination framework (ensemble signals with weighted voting)
- [ ] Strategy-level performance attribution in post-trade dashboard
- [ ] Strategy parameter auto-tuning via backtest grid search

### Phase 12 — Monitoring & Alerting
- [ ] Prometheus metrics exporter per service (latency, throughput, error rates)
- [ ] Grafana dashboards for system health (Kafka lag, fill latency, order book staleness)
- [ ] Risk breach alerts (max drawdown, position limit violations)
- [ ] Service heartbeat monitoring and dead-letter queue for failed messages
- [ ] Structured log aggregation (ELK or Loki)
- [ ] Alerting integration (PagerDuty, Slack webhook, or email)

### Phase 13 — Live Trading Prep
- [ ] Coinbase authenticated REST API adapter for real order placement
- [ ] Order lifecycle management (new → ack → partial fill → filled/cancelled)
- [ ] Position reconciliation against exchange balances
- [ ] Kill switch: emergency flat-all with single command
- [ ] Rate limiting and retry logic for exchange API
- [ ] Audit trail: immutable log of every order sent and fill received
- [ ] Deployment hardening: secrets management, TLS, health monitoring

## Design Decisions

**Microservice over monolith**: Each service is a separate Docker container communicating via Kafka. More complex to operate but isolates failures, enables independent scaling, and — critically — means the backtesting replay service can feed historical data through the same pipeline without any code changes.

**TimescaleDB over QuestDB/InfluxDB**: TimescaleDB is PostgreSQL underneath, so orders, fills, and metadata tables live in the same database and can JOIN with tick data using normal SQL. Purpose-built TSDBs would require a separate relational database.

**No numpy in the hot path**: The linear regression solver uses hand-rolled Gaussian elimination. numpy would be faster for large matrices but adds a heavy dependency and import time to the Alpha Engine. The C++ migration in Phase 6 will handle performance.

**Coinbase over Binance**: Binance's global API returns HTTP 451 for US IPs. Binance.US has very low volume. Coinbase is fully US-legal, no auth needed for public market data, and has good BTC-USD liquidity.

**Python 3.14**: Targets the latest stable release. The GIL is still present (free-threading not enabled), so parallelism comes from the microservice architecture (process-level) and asyncio (I/O-level). CPU-bound wins come from the C++ migration.
