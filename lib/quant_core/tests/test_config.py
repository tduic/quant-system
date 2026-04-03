"""Tests for quant_core.config — environment-based configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from quant_core.config import (
    AppConfig,
    CoinbaseConfig,
    DatabaseConfig,
    KafkaConfig,
    RedisConfig,
    _parse_symbols,
)


class TestKafkaConfig:
    def test_defaults(self):
        config = KafkaConfig()
        assert config.bootstrap_servers == "localhost:9092"
        assert config.producer_acks == "all"
        assert config.consumer_auto_offset_reset == "latest"
        assert config.consumer_enable_auto_commit is False

    def test_from_env_reads_bootstrap_servers(self):
        with patch.dict(os.environ, {"KAFKA_BOOTSTRAP_SERVERS": "kafka:29092"}):
            config = KafkaConfig.from_env()
            assert config.bootstrap_servers == "kafka:29092"

    def test_from_env_reads_consumer_group(self):
        with patch.dict(os.environ, {"KAFKA_CONSUMER_GROUP": "my-group"}):
            config = KafkaConfig.from_env()
            assert config.consumer_group_id == "my-group"

    def test_from_env_falls_back_to_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = KafkaConfig.from_env()
            assert config.bootstrap_servers == "localhost:9092"

    def test_frozen(self):
        config = KafkaConfig()
        with pytest.raises(AttributeError):
            config.bootstrap_servers = "new-value"


class TestRedisConfig:
    def test_defaults(self):
        config = RedisConfig()
        assert config.url == "redis://localhost:6379/0"

    def test_from_env(self):
        with patch.dict(os.environ, {"REDIS_URL": "redis://custom:6380/1"}):
            config = RedisConfig.from_env()
            assert config.url == "redis://custom:6380/1"


class TestDatabaseConfig:
    def test_defaults(self):
        config = DatabaseConfig()
        assert "quantdb" in config.url
        assert config.min_pool_size == 2
        assert config.max_pool_size == 10

    def test_from_env(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://user:pass@db:5432/mydb",
                "DB_MIN_POOL_SIZE": "5",
                "DB_MAX_POOL_SIZE": "20",
            },
        ):
            config = DatabaseConfig.from_env()
            assert config.url == "postgresql://user:pass@db:5432/mydb"
            assert config.min_pool_size == 5
            assert config.max_pool_size == 20


class TestParseSymbols:
    def test_single_symbol(self):
        with patch.dict(os.environ, {"SYMBOLS": "btcusdt"}):
            assert _parse_symbols() == ["btcusdt"]

    def test_multiple_symbols(self):
        with patch.dict(os.environ, {"SYMBOLS": "btcusdt,ethusdt,solusdt"}):
            result = _parse_symbols()
            assert result == ["btcusdt", "ethusdt", "solusdt"]

    def test_strips_whitespace(self):
        with patch.dict(os.environ, {"SYMBOLS": " btcusdt , ethusdt "}):
            result = _parse_symbols()
            assert result == ["btcusdt", "ethusdt"]

    def test_lowercases(self):
        with patch.dict(os.environ, {"SYMBOLS": "BTCUSDT"}):
            assert _parse_symbols() == ["btcusdt"]

    def test_default_is_btcusdt(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _parse_symbols() == ["btcusdt"]

    def test_empty_string_gives_empty_list(self):
        with patch.dict(os.environ, {"SYMBOLS": ""}):
            assert _parse_symbols() == []


class TestCoinbaseConfig:
    def test_defaults_to_empty_strings(self):
        config = CoinbaseConfig()
        assert config.api_key == ""
        assert config.api_secret == ""

    def test_from_env_reads_env_vars(self):
        with patch.dict(
            os.environ,
            {
                "COINBASE_API_KEY": "test-key-123",
                "COINBASE_API_SECRET": "test-secret-456",
            },
        ):
            config = CoinbaseConfig.from_env()
            assert config.api_key == "test-key-123"
            assert config.api_secret == "test-secret-456"

    def test_is_configured_returns_false_when_empty(self):
        config = CoinbaseConfig()
        assert config.is_configured is False

    def test_is_configured_returns_false_when_only_key_set(self):
        config = CoinbaseConfig(api_key="key", api_secret="")
        assert config.is_configured is False

    def test_is_configured_returns_false_when_only_secret_set(self):
        config = CoinbaseConfig(api_key="", api_secret="secret")
        assert config.is_configured is False

    def test_is_configured_returns_true_when_both_set(self):
        config = CoinbaseConfig(api_key="key", api_secret="secret")
        assert config.is_configured is True


class TestAppConfig:
    def test_from_env_creates_all_sub_configs(self):
        with patch.dict(
            os.environ,
            {
                "KAFKA_BOOTSTRAP_SERVERS": "kafka:29092",
                "REDIS_URL": "redis://redis:6379/0",
                "DATABASE_URL": "postgresql://q:q@db:5432/quantdb",
                "SYMBOLS": "btcusdt",
                "LOG_LEVEL": "DEBUG",
            },
        ):
            config = AppConfig.from_env()
            assert config.kafka.bootstrap_servers == "kafka:29092"
            assert config.redis.url == "redis://redis:6379/0"
            assert "quantdb" in config.database.url
            assert config.symbols == ["btcusdt"]
            assert config.log_level == "DEBUG"
            assert config.backtest_id is None

    def test_backtest_id_from_env(self):
        with patch.dict(os.environ, {"BACKTEST_ID": "abc-123"}):
            config = AppConfig.from_env()
            assert config.backtest_id == "abc-123"

    def test_from_env_includes_trading_mode_field(self):
        with patch.dict(os.environ, {"TRADING_MODE": "paper"}):
            config = AppConfig.from_env()
            assert config.trading_mode == "paper"

    def test_from_env_defaults_trading_mode_to_paper(self):
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.from_env()
            assert config.trading_mode == "paper"

    def test_from_env_accepts_live_trading_mode(self):
        with patch.dict(
            os.environ,
            {
                "TRADING_MODE": "live",
                "COINBASE_API_KEY": "test-key",
                "COINBASE_API_SECRET": "test-secret",
            },
        ):
            config = AppConfig.from_env()
            assert config.trading_mode == "live"

    def test_from_env_raises_error_when_live_without_coinbase_credentials(self):
        with patch.dict(os.environ, {"TRADING_MODE": "live"}, clear=True):
            with pytest.raises(ValueError) as excinfo:
                AppConfig.from_env()
            assert "COINBASE_API_KEY" in str(excinfo.value)
            assert "COINBASE_API_SECRET" in str(excinfo.value)

    def test_from_env_raises_error_when_live_without_api_key(self):
        with patch.dict(
            os.environ,
            {
                "TRADING_MODE": "live",
                "COINBASE_API_SECRET": "test-secret",
            },
        ):
            with pytest.raises(ValueError) as excinfo:
                AppConfig.from_env()
            assert "Live trading" in str(excinfo.value)

    def test_from_env_raises_error_when_live_without_api_secret(self):
        with patch.dict(
            os.environ,
            {
                "TRADING_MODE": "live",
                "COINBASE_API_KEY": "test-key",
            },
        ):
            with pytest.raises(ValueError) as excinfo:
                AppConfig.from_env()
            assert "Live trading" in str(excinfo.value)
