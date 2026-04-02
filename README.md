# Quant Trading System

A full-lifecycle quantitative trading system built as a microservice architecture. Covers the entire pipeline from data ingestion through post-trade analysis.

**Data Ingestion → Storage → Alpha Research → Risk Management → Execution → Post-Trade Analysis**

## Architecture

Seven microservices communicate via Kafka, with TimescaleDB for durable storage, Redis for shared state, and Prometheus + Grafana for monitoring.

```
Coinbase WebSocket                                         Coinbase REST API
       │                                                         ▲
       ▼                                                         │ (live mode)
┌──────────────┐    Kafka     ┌──────────────┐    Kafka     ┌──────────────┐
│  Market Data │──────────────│    Alpha     │──────────────│     Risk     │
│   Service    │  raw.trades  │    Engine    │   signals    │   Gateway    │
│              │  raw.depth   │              │              │  (Kill Switch│
└──────────────┘              └──────────────┘              │   API :8090) │
       │                             │                      └──────────────┘
       ▼                             │                            │
┌──────────────┐                     │                            │ orders
│   Storage    │                     │                            ▼
│   Service    │                     │                     ┌──────────────┐
│ (TimescaleDB)│                     │                     │  Execution   │
└──────────────┘                     │                     │   Service    │
                                     │                     └──────────────┘
                                     ▼                            │
                              ┌──────────────┐                    │ fills
                              │  Post-Trade  │◄───────────────────┘
                              │   Analysis   │──── Redis ────► Risk Gateway
                              │  (Dashboard) │  (portfolio      (reads state)
                              └──────────────┘   sync)
                                     │
                              ┌──────────────┐    ┌──────────────┐
                              │  Prometheus  │───▶│   Grafana    │
                              │   (:9091)    │    │   (:3001)    │
                              └──────────────┘    └──────────────┘
                              (scrapes /metrics from all services)
```

### Infrastructure

| Component    | Purpose                                            | Port  |
|-------------|-----------------------------------------------------|-------|
| Kafka       | Event bus between all services                      | 9092  |
| Zookeeper   | Kafka coordination                                  | 2181  |
| TimescaleDB | Time-series storage (trades, OHLCV, fills, audit)   | 5432  |
| Redis       | Shared state (positions, PnL, circuit breaker, orders) | 6379 |
| Prometheus  | Metrics collection and time-series storage          | 9091  |
| Grafana     | Metrics visualization and dashboards                | 3001  |

### Kafka Topics

| Topic              | Producer       | Consumer(s)              | Retention |
|--------------------|----------------|--------------------------|-----------|
| `raw.trades`       | Market Data    | Storage, Alpha Engine    | 7 days    |
| `raw.depth`        | Market Data    | Storage, Alpha, Execution| 3 days    |
| `signals`          | Alpha Engine   | Risk Gateway, Post-Trade | 30 days   |
| `orders`           | Risk Gateway   | Execution                | 30 days   |
| `fills`            | Execution      | Post-Trade               | 90 days   |
| `risk.events`      | Risk Gateway   | Post-Trade               | 90 days   |
| `order.status`     | Execution      | Post-Trade               | 90 days   |
| `audit.log`        | Risk, Execution| Storage                  | 365 days  |
| `system.heartbeat` | All services   | Monitoring               | 1 day     |

## Tech Stack

- **Language**: Python 3.14 (C++ via pybind11 for performance-critical paths)
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS + recharts
- **Messaging**: Apache Kafka (confluent-kafka)
- **Database**: TimescaleDB (PostgreSQL + time-series extensions)
- **Cache**: Redis
- **Containers**: Docker Compose
- **CI**: GitHub Actions
- **Monitoring**: Prometheus + Grafana
- **Linting**: Ruff (Python), ESLint 9 + TypeScript strict mode (frontend)
- **Testing**: pytest + pytest-cov

## Services

### Market Data Service
Connects to Coinbase WebSocket, normalizes trade and L2 order book data for multiple symbols (BTC-USD, ETH-USD, SOL-USD), publishes to Kafka. Handles reconnection with exponential backoff.

### Storage Service
Consumes from Kafka, batch-writes to TimescaleDB using the COPY protocol. TimescaleDB auto-generates 1-minute, 1-hour, and 1-day OHLCV candles via continuous aggregates. Compression kicks in after 7 days, retention drops raw data after 90 days.

### Alpha Engine
Consumes trades and depth updates, maintains per-symbol order books and a rolling feature engine (VWAP, volatility, trade imbalance, trade rate). Routes market data to pluggable strategies.

**Strategies:**
- **Mean Reversion** — Trades when price deviates from VWAP by a configurable z-score threshold. Includes warmup, cooldown, and duplicate suppression. One instance per symbol.
- **Linear Regression** — Rolling OLS fair value model. Regresses price against 4 features, trades the residual when it exceeds the threshold. Hand-rolled Gaussian elimination solver (no numpy).
- **Pairs Trading** — Mean-reversion on the log price ratio between two correlated assets. Uses a CrossAssetTracker for rolling correlation, relative strength, and spread z-score. Emits matched leg signals for both sides of the pair. Auto-registered for all C(n,2) symbol pairs.

### Risk Gateway
Consumes signals, runs composable risk checks, publishes approved orders or rejections. Reads real portfolio state from Redis (synced by the post-trade service after every fill) so risk limits are enforced against actual positions, not stale defaults. Includes a circuit breaker (kill switch) that halts all trading when tripped.

**Risk Checks:**
- Position size limit (per symbol)
- Order notional limit
- Max drawdown threshold
- Parametric VaR (GBM-based, configurable confidence/horizon)
- Total portfolio exposure (sum of abs notional across all symbols)
- Circuit breaker check (rejects all signals when tripped)

**Kill Switch HTTP API (port 8090):**
- `GET /api/circuit-breaker` — Current status (tripped/active, reason, timestamp)
- `POST /api/circuit-breaker/trip?reason=...` — Halt all trading immediately
- `POST /api/circuit-breaker/reset` — Resume trading
- `GET /health` — Service health with approval/rejection counters

Every approval and rejection is published to the `audit.log` Kafka topic for compliance.

### Execution Service
Consumes approved orders, routes them through paper or live execution based on `TRADING_MODE`, and publishes fill events. Manages full order lifecycle with state machine tracking (SUBMITTED → ACCEPTED → FILLED/CANCELLED). Checks the circuit breaker before processing any order.

**Trading Modes (`TRADING_MODE` env var):**
- `paper` (default) — Simulated fills using configurable fill models
- `live` — Routes orders to Coinbase Advanced Trade REST API with HMAC-SHA256 authentication, token-bucket rate limiting, and exponential backoff retry

**Fill Models (paper mode):**
- Simple spread model (mid +/- half spread)
- Walk-the-book (volume-weighted average across depth levels)
- Brownian bridge slippage (models price movement during order latency)

**Order Lifecycle:**
- `OrderTracker` persists order state to Redis with 7-day TTL
- `OrderStatusUpdate` events published to `order.status` Kafka topic
- Every fill and blocked order logged to `audit.log` topic

### Post-Trade Service
Consumes fills and trade data from Kafka, computes real-time analytics, and serves a FastAPI dashboard on port 8080. After every fill, syncs portfolio state (positions, equity, PnL) to Redis so the risk gateway always has current data.

**Dashboard Endpoints:**
- `GET /api/symbols` — Active symbols with positions or fills
- `GET /api/pnl[?symbol=X]` — PnL attribution (per symbol, realized + unrealized)
- `GET /api/tca[?symbol=X]` — Transaction cost analysis (per-fill breakdown + averages)
- `GET /api/alpha-decay[?symbol=X]` — IC decay curves at 5 horizons (1m, 5m, 15m, 30m, 1h), per-strategy breakdown
- `GET /api/risk-metrics` — Sharpe, Sortino, Calmar, drawdown, win rate, profit factor
- `GET /api/drawdown` — Equity curve + running drawdown curve
- `GET /api/fills[?symbol=X]` — Fill details + summary stats
- `GET /api/export/excel` — Download formatted .xlsx report (5 sheets)

**Analysis Endpoints (async job runner):**
- `POST /api/analysis/submit` — Submit an analysis job (sensitivity, walk-forward, monte-carlo, cost-sweep, validate, run-all)
- `GET /api/analysis/status/{job_id}` — Poll job progress (0-100%)
- `GET /api/analysis/result/{job_id}` — Fetch completed results
- `GET /api/analysis/jobs` — List all jobs
- `GET /api/analysis/backtests` — List historical backtest runs with trade data

All filterable endpoints accept an optional `?symbol=` query parameter for per-symbol views.

### Dashboard Frontend
React 19 + TypeScript SPA served via nginx on port 3000 (Docker) or Vite dev server. Features 7 tabs: P&L, TCA, Alpha Decay, Risk Metrics, Drawdown, Fills, and Analysis. Auto-refreshing data every 5 seconds, equity/drawdown charts with recharts, a symbol selector dropdown for filtering across tabs, and an Excel download button. In Docker, nginx reverse-proxies `/api/` to the post-trade FastAPI backend.

The Analysis tab provides a dashboard for running all backtest analysis types (sensitivity, walk-forward, Monte Carlo, cost sweep, validation, or all at once). Supports choosing between synthetic generated data or historical data from previous backtest runs, with live progress bars and rich result renderers per analysis type.

### Backtest Service
Replays historical tick data from TimescaleDB through the same Kafka pipeline with a `backtest_id` header. All downstream services process backtest data identically to live — no `if backtest:` branches. Three replay modes: as_fast_as_possible, real_time, and scaled (Nx speed).

```bash
make backtest ARGS="--symbol BTCUSD --start 2026-03-21T00:00:00 --end 2026-03-21T12:00:00"
make backtest-list
make backtest-results ID=bt-abc123
```

**Backtest Analysis Modules:**
- **Walk-Forward Optimization** — Rolling or expanding train/test windows with parameter optimization per fold. Detects overfitting via train-vs-test Sharpe degradation.
- **Parameter Sensitivity** — Grid search and random search over strategy parameters. Computes per-parameter impact scores and Pearson correlation with Sharpe.
- **Monte Carlo Simulation** — Bootstrap and block-bootstrap resampling of return series. Produces confidence intervals on Sharpe, max drawdown, and total return.
- **Backtest Comparison** — Side-by-side metrics for multiple runs with pairwise deltas, percent changes, and ranking by Sharpe or return.
- **Slippage/Fee Sensitivity** — Sweeps fee rates, slippage (bps), and latency to find breakeven thresholds and compute dSharpe/dCost sensitivities.
- **Out-of-Sample Validation** — Combines walk-forward, Monte Carlo, and cost sensitivity results into a composite grade (STRONG/MODERATE/WEAK/FAIL) with categorical flags.

## Circuit Breaker (Kill Switch)

A Redis-backed circuit breaker checked by all trading services. When tripped, the alpha engine suppresses signal emission (but continues updating model state), the risk gateway rejects all signals, and the execution service blocks all orders. The breaker uses a local cache with 0.5-second TTL to minimize Redis load and fails safe — if Redis is unreachable, it assumes the breaker is tripped.

```bash
# Trip the kill switch (halt all trading immediately)
curl -X POST "http://localhost:8090/api/circuit-breaker/trip?reason=manual+halt&triggered_by=operator"

# Check status
curl http://localhost:8090/api/circuit-breaker

# Resume trading
curl -X POST "http://localhost:8090/api/circuit-breaker/reset?reset_by=operator"
```

## Monitoring & Alerting

Every service exposes a `/metrics` endpoint in Prometheus text exposition format (port 9090 inside the container) and a `/health` endpoint. Prometheus scrapes all services every 15 seconds and stores metrics with 30-day retention.

- **Prometheus**: http://localhost:9091 — query metrics, check targets
- **Grafana**: http://localhost:3001 — dashboards (default login: admin / admin)
- **Alertmanager**: http://localhost:9093 — alert status and silences

Two dashboards are auto-provisioned on startup: **Trading Overview** (equity curve, drawdown, fill rates, slippage, PnL, rejection reasons, circuit breaker status) and **Service Health** (per-service throughput, up/down status, trade processing rates). The Prometheus datasource is also auto-configured.

**Alert rules** fire on circuit breaker trips, drawdown breaches (>3% warning, >5% critical), service outages, market data gaps, high rejection rates, and excessive slippage. Alerts route to Slack via an incoming webhook — set `SLACK_WEBHOOK_URL` in `.env`.

**Instrumented metrics across all services:** `messages_published` (market data), `trades_processed` and `signals_emitted` (alpha engine), `orders_approved`, `orders_rejected`, `portfolio_equity`, `portfolio_drawdown_pct` (risk gateway), `fills_total`, `fill_slippage_bps`, `fill_fee` (execution), `fills_processed`, `portfolio_realized_pnl`, `portfolio_unrealized_pnl`, `portfolio_total_fees` (post-trade), and `circuit_breaker_active` (all services).

## Paper Trading Validation

Before switching to live trading, run the validation framework to verify system health:

```bash
make validate                # single-pass check (exit code 0/1)
make validate-continuous     # 5-minute continuous validation
make validate-long           # 1-hour validation with 60s intervals
```

The validator checks Redis connectivity, circuit breaker status, risk gateway health, portfolio state, fill quality (slippage stats, fee sanity), PnL consistency, drawdown limits, and order tracking. The continuous modes run repeated snapshots and generate a JSON report.

## Database Tables

Beyond the core `trades`, `order_book_snapshots`, `orders`, and `fills` hypertables, the system includes:

| Table                      | Purpose                                        | Chunks    |
|----------------------------|------------------------------------------------|-----------|
| `order_status_history`     | Append-only order lifecycle events              | 7-day     |
| `audit_log`                | Immutable audit trail (JSONB detail)            | 7-day     |
| `reconciliation_history`   | Internal-vs-exchange balance comparisons        | 30-day    |

## Quick Start

### Prerequisites
- Docker Desktop (running)
- Python 3.14
- Git

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/quant-system.git
cd quant-system

# Configure environment
cp .env.example .env
# Edit .env — at minimum, set POSTGRES_PASSWORD for production
# For live trading, set TRADING_MODE=live and provide COINBASE_API_KEY / COINBASE_API_SECRET

# Python environment
python3.14 -m venv venv
source venv/bin/activate
pip install -e lib/
pip install -r requirements-test.txt
```

### Run

```bash
make up                    # start everything (cached)
make up-build              # start everything (rebuild images)
make logs                  # watch output
make db-trade-count        # verify data is flowing
```

The dashboard is at http://localhost:3000, the API at http://localhost:8080, Prometheus at http://localhost:9091, and Grafana at http://localhost:3001.

### Stop

```bash
make down                  # stop containers (data persists)
make clean                 # stop and delete all data
```

### Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and adjust values. Key variables:

| Variable               | Default          | Description                                    |
|------------------------|------------------|------------------------------------------------|
| `TRADING_MODE`         | `paper`          | `paper` for simulated fills, `live` for Coinbase |
| `COINBASE_API_KEY`     | (empty)          | Required for live trading and reconciliation    |
| `COINBASE_API_SECRET`  | (empty)          | Required for live trading and reconciliation    |
| `SYMBOLS`              | `btcusd,ethusd,solusd` | Comma-separated trading symbols           |
| `POSTGRES_PASSWORD`    | `quant_dev`      | Database password (change for production)       |
| `MAX_POSITION_SIZE`    | `1.0`            | Max position per symbol (in base units)         |
| `MAX_ORDER_NOTIONAL`   | `100000`         | Max single order value (USD)                    |
| `MAX_DRAWDOWN_PCT`     | `0.05`           | Max portfolio drawdown before risk rejection    |
| `MAX_TOTAL_EXPOSURE`   | `500000`         | Max total abs notional across all symbols       |
| `LOG_LEVEL`            | `INFO`           | Python log level for all services               |

The system fails fast on startup if `TRADING_MODE=live` is set without valid Coinbase API credentials.

## Commands Reference

### Docker Compose

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make up`            | Start all services (infra + microservices)         |
| `make up-infra`      | Start only infrastructure (Kafka, TimescaleDB, Redis) |
| `make up-market-data`| Start market data service only                     |
| `make up-storage`    | Start storage service only                         |
| `make down`          | Stop all containers                                |
| `make restart`       | Restart all containers                             |
| `make build`         | Rebuild Docker images (needed after code changes)  |
| `make status`        | Show which containers are running                  |
| `make logs`          | Tail logs from all services                        |
| `make logs-market-data` | Tail market data logs only                      |
| `make logs-storage`  | Tail storage logs only                             |

### Database (TimescaleDB)

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make db-shell`      | Open a psql prompt into TimescaleDB                |
| `make db-trade-count`| Count stored trades per symbol                     |
| `make db-ohlcv`      | Show the latest 1-minute OHLCV candle bars         |
| `make db-book-count` | Count order book snapshots                         |
| `make db-schema`     | Show hypertables and compression status            |

### Kafka

| Command                  | Description                                   |
|--------------------------|-----------------------------------------------|
| `make kafka-topics`      | List all Kafka topics                          |
| `make kafka-consume-trades` | Print 10 messages from the trades topic     |
| `make kafka-consume-depth`  | Print 5 messages from the depth topic       |
| `make kafka-offsets`     | Show consumer group lag/offsets                |

### Redis

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make redis-cli`     | Open an interactive Redis shell                    |
| `make redis-keys`    | List all keys currently in Redis                   |

### Testing

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make test`          | Run all unit tests                                 |
| `make test-cov`      | Run tests with coverage report                     |
| `make test-lib`      | Run shared library tests only                      |
| `make test-market-data` | Run market data tests only                      |
| `make test-storage`  | Run storage tests only                             |
| `make test-alpha`    | Run alpha engine tests only                        |
| `make test-risk`     | Run risk gateway tests only                        |
| `make test-execution`| Run execution service tests only                   |
| `make test-post-trade` | Run post-trade tests only                        |
| `make test-backtest` | Run backtest service tests only                    |
| `make test-watch`    | Auto-rerun tests on file changes                   |

### Backtesting

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make backtest ARGS="..."` | Run a backtest (see args below)              |
| `make backtest-list` | List all stored backtest runs                      |
| `make backtest-results ID=bt-...` | Show results for a specific run        |

Backtest args: `--symbol BTCUSD --start 2026-03-21T00:00:00 --end 2026-03-21T12:00:00 [--speed as_fast_as_possible|real_time|scaled] [--multiplier 10] [--no-depth]`

### C++ (pybind11)

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make cpp-build`     | Build C++ with CMake (native tests only)           |
| `make cpp-install`   | Install quant_cpp module into current Python env   |
| `make cpp-test`      | Run C++ native tests (builds first if needed)      |
| `make test-cpp`      | Run Python tests for C++ module                    |
| `make cpp-benchmark` | Run Python vs C++ performance comparison           |
| `make cpp-clean`     | Clean C++ build artifacts                          |

To use C++ acceleration:
```bash
make cpp-install      # one-time: compile and install the .so
make cpp-benchmark    # see the speedup numbers
```

### Frontend (React Dashboard)

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make fe-install`    | Install frontend npm dependencies                  |
| `make fe-dev`        | Start Vite dev server (localhost:3000, proxies API to :8080) |
| `make fe-build`      | Build frontend for production                      |
| `make fe-lint`       | Type-check frontend with TypeScript                |

### Linting & Formatting

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make lint`          | Check code with ruff (no changes)                  |
| `make lint-fix`      | Auto-fix linting issues                            |
| `make format`        | Format code with ruff                              |

### Cleanup

| Command              | Description                                       |
|----------------------|---------------------------------------------------|
| `make clean`         | Stop everything and delete all data volumes        |
| `make clean-images`  | Remove built Docker images                         |

## Project Structure

```
quant-system/
├── lib/quant_core/              # Shared library
│   ├── models.py                #   Trade, DepthUpdate, Signal, Order, Fill, OrderStatusUpdate
│   ├── kafka_utils.py           #   QProducer, QConsumer with backtest_id injection
│   ├── redis_utils.py           #   Key schema and connection factories
│   ├── config.py                #   Environment-based config (AppConfig, CoinbaseConfig)
│   ├── logging.py               #   Structured JSON logging
│   ├── circuit_breaker.py       #   Redis-backed kill switch with local cache
│   ├── portfolio_state.py       #   Portfolio sync between post-trade and risk gateway
│   ├── coinbase_rest.py         #   Coinbase Advanced Trade REST client (HMAC-SHA256)
│   ├── rate_limiter.py          #   Token bucket rate limiter + retry policy
│   ├── reconciliation.py        #   Internal-vs-exchange position reconciliation
│   ├── metrics.py               #   Prometheus-compatible metrics registry
│   └── accelerated.py           #   C++ import switching (tries pybind11, falls back to Python)
├── services/
│   ├── market-data/             # Coinbase WebSocket → Kafka
│   │   └── market_data_svc/
│   ├── storage/                 # Kafka → TimescaleDB (batch COPY)
│   │   └── storage_svc/
│   ├── alpha-engine/            # Strategies, order book, feature engine
│   │   └── alpha_engine_svc/
│   │       ├── cross_asset.py   #   CrossAssetTracker (correlation, relative strength, spread z)
│   │       └── strategies/      #   mean_reversion.py, linear_regression.py, pairs_trading.py
│   ├── risk-gateway/            # Risk checks, VaR, kill switch API
│   │   └── risk_gateway_svc/
│   ├── execution/               # Paper + live execution, order lifecycle
│   │   └── execution_svc/
│   │       ├── fill_simulator.py #  Paper trading fill models
│   │       └── order_tracker.py  #  Order state machine (Redis-persisted)
│   ├── post-trade/              # PnL, metrics, TCA, analysis, FastAPI dashboard
│   │   ├── post_trade_svc/
│   │   │   └── analysis_jobs.py #  Async analysis job runner
│   │   └── frontend/            # React + TypeScript dashboard (Vite, Tailwind, recharts)
│   └── backtest/                # Replay engine + CLI + analysis modules
│       └── backtest_svc/
├── cpp/                         # C++ pybind11 accelerated modules
├── monitoring/
│   └── prometheus.yml           # Prometheus scrape configuration
├── scripts/
│   ├── init_db.sql              # TimescaleDB schema, hypertables, aggregates, audit tables
│   └── create_topics.sh         # Kafka topic creation (9 topics)
├── .env.example                 # Environment variable template
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── .github/workflows/ci.yml
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full implementation plan.
