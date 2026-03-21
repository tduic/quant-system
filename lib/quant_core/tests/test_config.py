"""Tests for quant_core.config — environment-based configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from quant_core.config import (
    AppConfig,
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
