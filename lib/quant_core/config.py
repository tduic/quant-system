"""Centralized configuration management.

All services read config from environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: str = "localhost:9092"
    # Producer
    producer_acks: str = "all"
    producer_linger_ms: int = 5
    producer_batch_size: int = 16384
    # Consumer
    consumer_group_id: str = "default-group"
    consumer_auto_offset_reset: str = "latest"
    consumer_enable_auto_commit: bool = False
    consumer_max_poll_records: int = 500

    @classmethod
    def from_env(cls, prefix: str = "") -> KafkaConfig:
        return cls(
            bootstrap_servers=os.getenv(
                f"{prefix}KAFKA_BOOTSTRAP_SERVERS", cls.bootstrap_servers
            ),
            consumer_group_id=os.getenv(
                f"{prefix}KAFKA_CONSUMER_GROUP", cls.consumer_group_id
            ),
            consumer_auto_offset_reset=os.getenv(
                f"{prefix}KAFKA_AUTO_OFFSET_RESET", cls.consumer_auto_offset_reset
            ),
        )


@dataclass(frozen=True)
class RedisConfig:
    url: str = "redis://localhost:6379/0"

    @classmethod
    def from_env(cls) -> RedisConfig:
        return cls(url=os.getenv("REDIS_URL", cls.url))


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = "postgresql://quant:quant_dev@localhost:5432/quantdb"
    min_pool_size: int = 2
    max_pool_size: int = 10

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        return cls(
            url=os.getenv("DATABASE_URL", cls.url),
            min_pool_size=int(os.getenv("DB_MIN_POOL_SIZE", str(cls.min_pool_size))),
            max_pool_size=int(os.getenv("DB_MAX_POOL_SIZE", str(cls.max_pool_size))),
        )


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config combining all sub-configs."""

    kafka: KafkaConfig = field(default_factory=KafkaConfig.from_env)
    redis: RedisConfig = field(default_factory=RedisConfig.from_env)
    database: DatabaseConfig = field(default_factory=DatabaseConfig.from_env)
    symbols: list[str] = field(default_factory=lambda: _parse_symbols())
    log_level: str = "INFO"
    backtest_id: str | None = None

    @classmethod
    def from_env(cls) -> AppConfig:
        return cls(
            kafka=KafkaConfig.from_env(),
            redis=RedisConfig.from_env(),
            database=DatabaseConfig.from_env(),
            symbols=_parse_symbols(),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            backtest_id=os.getenv("BACKTEST_ID"),
        )


def _parse_symbols() -> list[str]:
    raw = os.getenv("SYMBOLS", "btcusdt")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]
