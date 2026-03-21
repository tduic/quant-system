-- ==========================================================================
-- Quant Trading System — Database Initialization
-- Runs automatically on first TimescaleDB container start
-- ==========================================================================

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ==========================================================================
-- Metadata tables (standard PostgreSQL)
-- ==========================================================================

CREATE TABLE IF NOT EXISTS symbols (
    symbol_id   SERIAL PRIMARY KEY,
    symbol      VARCHAR(20) UNIQUE NOT NULL,
    exchange    VARCHAR(20) NOT NULL DEFAULT 'binance',
    base_asset  VARCHAR(10) NOT NULL,
    quote_asset VARCHAR(10) NOT NULL,
    tick_size   DECIMAL(18,8),
    lot_size    DECIMAL(18,8),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Seed BTC/USD (Coinbase)
INSERT INTO symbols (symbol, exchange, base_asset, quote_asset, tick_size, lot_size)
VALUES ('BTCUSD', 'coinbase', 'BTC', 'USD', 0.01, 0.00000001)
ON CONFLICT (symbol) DO NOTHING;

-- ==========================================================================
-- Raw trades hypertable
-- ==========================================================================

CREATE TABLE IF NOT EXISTS trades (
    time                TIMESTAMPTZ     NOT NULL,
    symbol              VARCHAR(20)     NOT NULL,
    trade_id            BIGINT          NOT NULL,
    price               DECIMAL(18,8)   NOT NULL,
    quantity            DECIMAL(18,8)   NOT NULL,
    is_buyer_maker      BOOLEAN         NOT NULL,
    ingestion_latency_us INTEGER,
    backtest_id         UUID
);

SELECT create_hypertable('trades', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
    ON trades (symbol, time DESC);

CREATE INDEX IF NOT EXISTS idx_trades_backtest
    ON trades (backtest_id, time DESC)
    WHERE backtest_id IS NOT NULL;

-- ==========================================================================
-- Order book snapshots hypertable
-- ==========================================================================

CREATE TABLE IF NOT EXISTS order_book_snapshots (
    time            TIMESTAMPTZ     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    bid_prices      DECIMAL(18,8)[] NOT NULL,
    bid_sizes       DECIMAL(18,8)[] NOT NULL,
    ask_prices      DECIMAL(18,8)[] NOT NULL,
    ask_sizes       DECIMAL(18,8)[] NOT NULL,
    spread          DECIMAL(18,8)   NOT NULL,
    mid_price       DECIMAL(18,8)   NOT NULL,
    backtest_id     UUID
);

SELECT create_hypertable('order_book_snapshots', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_obs_symbol_time
    ON order_book_snapshots (symbol, time DESC);

-- ==========================================================================
-- Orders table
-- ==========================================================================

CREATE TABLE IF NOT EXISTS orders (
    order_id        UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    time            TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(4)      NOT NULL,
    order_type      VARCHAR(10)     NOT NULL,
    quantity        DECIMAL(18,8)   NOT NULL,
    limit_price     DECIMAL(18,8),
    status          VARCHAR(20)     NOT NULL DEFAULT 'SUBMITTED',
    signal_id       UUID,
    backtest_id     UUID,
    strategy_id     VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_orders_symbol_time
    ON orders (symbol, time DESC);

CREATE INDEX IF NOT EXISTS idx_orders_backtest
    ON orders (backtest_id, time DESC)
    WHERE backtest_id IS NOT NULL;

-- ==========================================================================
-- Fills hypertable
-- ==========================================================================

CREATE TABLE IF NOT EXISTS fills (
    fill_id         UUID            NOT NULL DEFAULT gen_random_uuid(),
    time            TIMESTAMPTZ     NOT NULL,
    order_id        UUID            NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(4)      NOT NULL,
    quantity        DECIMAL(18,8)   NOT NULL,
    fill_price      DECIMAL(18,8)   NOT NULL,
    fee             DECIMAL(18,8)   DEFAULT 0,
    slippage_bps    DECIMAL(10,4),
    backtest_id     UUID,
    strategy_id     VARCHAR(50),
    PRIMARY KEY (fill_id, time)
);

SELECT create_hypertable('fills', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_fills_order
    ON fills (order_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_fills_backtest
    ON fills (backtest_id, time DESC)
    WHERE backtest_id IS NOT NULL;

-- ==========================================================================
-- Continuous Aggregates: OHLCV bars from raw trades
-- ==========================================================================

-- 1-minute OHLCV
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time)   AS bucket,
    symbol,
    first(price, time)              AS open,
    max(price)                      AS high,
    min(price)                      AS low,
    last(price, time)               AS close,
    sum(quantity)                    AS volume,
    count(*)                        AS trade_count,
    sum(price * quantity)           AS quote_volume
FROM trades
WHERE backtest_id IS NULL
GROUP BY bucket, symbol
WITH NO DATA;

-- Refresh policy: refresh the last 10 minutes every 1 minute
SELECT add_continuous_aggregate_policy('ohlcv_1m',
    start_offset    => INTERVAL '10 minutes',
    end_offset      => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists   => TRUE
);

-- 1-hour OHLCV (built directly from trades — no hierarchical dependency)
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time)     AS bucket,
    symbol,
    first(price, time)              AS open,
    max(price)                      AS high,
    min(price)                      AS low,
    last(price, time)               AS close,
    sum(quantity)                    AS volume,
    count(*)                        AS trade_count,
    sum(price * quantity)           AS quote_volume
FROM trades
WHERE backtest_id IS NULL
GROUP BY bucket, symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_1h',
    start_offset    => INTERVAL '4 hours',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists   => TRUE
);

-- 1-day OHLCV (built directly from trades)
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1d
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time)      AS bucket,
    symbol,
    first(price, time)              AS open,
    max(price)                      AS high,
    min(price)                      AS low,
    last(price, time)               AS close,
    sum(quantity)                    AS volume,
    count(*)                        AS trade_count,
    sum(price * quantity)           AS quote_volume
FROM trades
WHERE backtest_id IS NULL
GROUP BY bucket, symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_1d',
    start_offset    => INTERVAL '4 days',
    end_offset      => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists   => TRUE
);

-- ==========================================================================
-- Compression Policies
-- ==========================================================================

ALTER TABLE trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('trades',
    compress_after => INTERVAL '7 days',
    if_not_exists  => TRUE
);

ALTER TABLE order_book_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('order_book_snapshots',
    compress_after => INTERVAL '7 days',
    if_not_exists  => TRUE
);

ALTER TABLE fills SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('fills',
    compress_after => INTERVAL '30 days',
    if_not_exists  => TRUE
);

-- ==========================================================================
-- Retention Policies
-- ==========================================================================

SELECT add_retention_policy('trades',
    drop_after     => INTERVAL '90 days',
    if_not_exists  => TRUE
);

SELECT add_retention_policy('order_book_snapshots',
    drop_after     => INTERVAL '90 days',
    if_not_exists  => TRUE
);

-- Fills kept for 1 year (needed for post-trade analysis)
SELECT add_retention_policy('fills',
    drop_after     => INTERVAL '365 days',
    if_not_exists  => TRUE
);

-- ==========================================================================
-- Done
-- ==========================================================================

DO $$
BEGIN
    RAISE NOTICE '=== Quant DB initialization complete ===';
END $$;
