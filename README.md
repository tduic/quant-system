# Quant Trading System

A full-lifecycle quantitative trading system built as a microservice architecture. Covers the entire pipeline from data ingestion through post-trade analysis.

**Data Ingestion → Storage → Alpha Research → Risk Management → Execution → Post-Trade Analysis**

## Architecture

Six microservices communicate via Kafka, with TimescaleDB for durable storage and Redis for shared state.

```
Coinbase WebSocket
       │
       ▼
┌──────────────┐    Kafka     ┌──────────────┐    Kafka     ┌──────────────┐
│  Market Data │──────────────│    Alpha     │──────────────│     Risk     │
│   Service    │  raw.trades  │    Engine    │   signals    │   Gateway    │
│              │  raw.depth   │              │              │              │
└──────────────┘              └──────────────┘              └──────────────┘
       │                             │                            │
       ▼                             │                            │ orders
┌──────────────┐                     │                            ▼
│   Storage    │                     │                     ┌──────────────┐
│   Service    │                     │                     │  Execution   │
│ (TimescaleDB)│                     │                     │   Service    │
└──────────────┘                     │                     └──────────────┘
                                     │                            │
                                     ▼                            │ fills
                              ┌──────────────┐                    │
                              │  Post-Trade  │◄───────────────────┘
                              │   Analysis   │
                              │  (Dashboard) │
                              └──────────────┘
```

### Infrastructure

| Component    | Purpose                                   | Port  |
|-------------|-------------------------------------------|-------|
| Kafka       | Event bus between all services             | 9092  |
| Zookeeper   | Kafka coordination                        | 2181  |
| TimescaleDB | Time-series storage (trades, OHLCV, fills)| 5432  |
| Redis       | Shared state (positions, live PnL)        | 6379  |

### Kafka Topics

| Topic             | Producer       | Consumer(s)              |
|-------------------|----------------|--------------------------|
| `raw.trades`      | Market Data    | Storage, Alpha Engine    |
| `raw.depth`       | Market Data    | Storage, Alpha, Execution|
| `signals`         | Alpha Engine   | Risk Gateway             |
| `orders`          | Risk Gateway   | Execution                |
| `fills`           | Execution      | Post-Trade               |
| `risk.events`     | Risk Gateway   | Post-Trade               |
| `system.heartbeat`| All services   | Monitoring               |

## Tech Stack

- **Language**: Python 3.14 (C++ via pybind11 for performance-critical paths)
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS + recharts
- **Messaging**: Apache Kafka (confluent-kafka)
- **Database**: TimescaleDB (PostgreSQL + time-series extensions)
- **Cache**: Redis
- **Containers**: Docker Compose
- **CI**: GitHub Actions
- **Linting**: Ruff (Python), TypeScript strict mode (frontend)
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
Consumes signals, runs composable risk checks, publishes approved orders or rejections.

**Risk Checks:**
- Position size limit (per symbol)
- Order notional limit
- Max drawdown threshold
- Parametric VaR (GBM-based, configurable confidence/horizon)
- Total portfolio exposure (sum of abs notional across all symbols)

### Execution Service
Consumes approved orders, simulates fills for paper trading, publishes fill events.

**Fill Models:**
- Simple spread model (mid +/- half spread)
- Walk-the-book (volume-weighted average across depth levels)
- Brownian bridge slippage (models price movement during order latency)

### Post-Trade Service
Consumes fills and trade data from Kafka, computes real-time analytics, and serves a FastAPI dashboard on port 8080.

**Dashboard Endpoints:**
- `GET /api/symbols` — Active symbols with positions or fills
- `GET /api/pnl[?symbol=X]` — PnL attribution (per symbol, realized + unrealized)
- `GET /api/tca[?symbol=X]` — Transaction cost analysis (per-fill breakdown + averages)
- `GET /api/alpha-decay[?symbol=X]` — IC decay curves at 5 horizons (1m, 5m, 15m, 30m, 1h), per-strategy breakdown
- `GET /api/risk-metrics` — Sharpe, Sortino, Calmar, drawdown, win rate, profit factor
- `GET /api/drawdown` — Equity curve + running drawdown curve
- `GET /api/fills[?symbol=X]` — Fill details + summary stats
- `GET /api/export/excel` — Download formatted .xlsx report (5 sheets)

All filterable endpoints accept an optional `?symbol=` query parameter for per-symbol views.

### Dashboard Frontend
React 19 + TypeScript SPA served via nginx on port 3000 (Docker) or Vite dev server. Features 6 tabs matching the FastAPI endpoints, auto-refreshing data every 5 seconds, equity/drawdown charts with recharts, a symbol selector dropdown for filtering across tabs, and an Excel download button. In Docker, nginx reverse-proxies `/api/` to the post-trade FastAPI backend.

### Backtest Service
Replays historical tick data from TimescaleDB through the same Kafka pipeline with a `backtest_id` header. All downstream services process backtest data identically to live — no `if backtest:` branches. Three replay modes: as_fast_as_possible, real_time, and scaled (Nx speed).

```bash
make backtest ARGS="--symbol BTCUSD --start 2026-03-21T00:00:00 --end 2026-03-21T12:00:00"
make backtest-list
make backtest-results ID=bt-abc123
```

## Quick Start

### Prerequisites
- Docker Desktop (running)
- Python 3.14
- Git

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/quant-system.git
cd quant-system
python3.14 -m venv venv
source venv/bin/activate
pip install -e lib/
pip install -r requirements-test.txt
```

### Run

```bash
make up                    # start everything
make logs                  # watch output
make db-trade-count        # verify data is flowing
```

### Stop

```bash
make down                  # stop containers (data persists)
make clean                 # stop and delete all data
```

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
├── lib/quant_core/              # Shared library (models, Kafka/Redis helpers, config)
│   ├── models.py                #   Trade, DepthUpdate, Signal, Order, Fill, RiskDecision
│   ├── kafka_utils.py           #   QProducer, QConsumer with backtest_id injection
│   ├── redis_utils.py           #   Key schema and connection factories
│   ├── config.py                #   Environment-based config
│   └── logging.py               #   Structured JSON logging
├── services/
│   ├── market-data/             # Coinbase WebSocket → Kafka
│   │   └── market_data_svc/
│   ├── storage/                 # Kafka → TimescaleDB (batch COPY)
│   │   └── storage_svc/
│   ├── alpha-engine/            # Strategies, order book, feature engine
│   │   └── alpha_engine_svc/
│   │       ├── cross_asset.py   #   CrossAssetTracker (correlation, relative strength, spread z)
│   │       └── strategies/      #   mean_reversion.py, linear_regression.py, pairs_trading.py
│   ├── risk-gateway/            # Risk checks, VaR model
│   │   └── risk_gateway_svc/
│   ├── execution/               # Fill simulator (spread, walk-book, Brownian bridge)
│   │   └── execution_svc/
│   ├── post-trade/              # PnL, metrics, TCA, FastAPI dashboard
│   │   ├── post_trade_svc/
│   │   └── frontend/            # React + TypeScript dashboard (Vite, Tailwind, recharts)
│   └── backtest/                # Replay engine + CLI
│       └── backtest_svc/
├── scripts/
│   ├── init_db.sql              # TimescaleDB schema, hypertables, aggregates
│   └── create_topics.sh         # Kafka topic creation
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── .github/workflows/ci.yml
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full implementation plan.
