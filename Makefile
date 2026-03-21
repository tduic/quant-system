.PHONY: help up down logs status ps db-shell kafka-topics kafka-consume-trades redis-cli clean build restart test test-cov test-lib test-market-data test-storage test-alpha test-risk test-execution test-post-trade test-watch

# Default target
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------

build: ## Build all service images
	docker compose build

up: ## Start all services (infra + services)
	docker compose up -d
	@echo ""
	@echo "=== Quant system starting ==="
	@echo "  TimescaleDB:  localhost:5432"
	@echo "  Kafka:        localhost:9092"
	@echo "  Redis:        localhost:6379"
	@echo "  Dashboard:    localhost:8080 (when post-trade is running)"
	@echo ""
	@echo "Run 'make logs' to follow service output"

up-infra: ## Start only infrastructure (Kafka, TimescaleDB, Redis)
	docker compose up -d zookeeper kafka kafka-init timescaledb redis

up-market-data: ## Start market data service only
	docker compose up -d market-data

up-storage: ## Start storage service only
	docker compose up -d storage

down: ## Stop all services
	docker compose down

restart: ## Restart all services
	docker compose restart

logs: ## Follow logs from all services
	docker compose logs -f

logs-market-data: ## Follow market data service logs
	docker compose logs -f market-data

logs-storage: ## Follow storage service logs
	docker compose logs -f storage

status: ## Show service status
	docker compose ps

ps: status ## Alias for status

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db-shell: ## Open psql shell to TimescaleDB
	docker compose exec timescaledb psql -U quant -d quantdb

db-trade-count: ## Count trades in the database
	docker compose exec timescaledb psql -U quant -d quantdb -c \
		"SELECT symbol, count(*), min(time), max(time) FROM trades GROUP BY symbol;"

db-ohlcv: ## Show latest 1-minute OHLCV bars
	docker compose exec timescaledb psql -U quant -d quantdb -c \
		"SELECT * FROM ohlcv_1m ORDER BY bucket DESC LIMIT 10;"

db-book-count: ## Count order book snapshots
	docker compose exec timescaledb psql -U quant -d quantdb -c \
		"SELECT symbol, count(*), min(time), max(time) FROM order_book_snapshots GROUP BY symbol;"

db-schema: ## Show all tables and hypertables
	docker compose exec timescaledb psql -U quant -d quantdb -c \
		"SELECT hypertable_name, num_chunks, compression_enabled FROM timescaledb_information.hypertables;"

# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------

kafka-topics: ## List all Kafka topics
	docker compose exec kafka kafka-topics --list --bootstrap-server localhost:9092

kafka-consume-trades: ## Consume from raw.trades topic (Ctrl+C to stop)
	docker compose exec kafka kafka-console-consumer \
		--bootstrap-server localhost:9092 \
		--topic raw.trades \
		--from-beginning \
		--max-messages 10

kafka-consume-depth: ## Consume from raw.depth topic
	docker compose exec kafka kafka-console-consumer \
		--bootstrap-server localhost:9092 \
		--topic raw.depth \
		--from-beginning \
		--max-messages 5

kafka-offsets: ## Show consumer group offsets
	docker compose exec kafka kafka-consumer-groups \
		--bootstrap-server localhost:9092 \
		--describe --all-groups

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

redis-cli: ## Open Redis CLI
	docker compose exec redis redis-cli

redis-keys: ## List all Redis keys
	docker compose exec redis redis-cli KEYS '*'

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: ## Run all unit tests
	python -m pytest

test-cov: ## Run tests with coverage report
	python -m pytest --cov --cov-report=term-missing --cov-report=html:htmlcov

test-lib: ## Run shared library tests only
	python -m pytest lib/quant_core/tests/ -v

test-market-data: ## Run market data service tests only
	python -m pytest services/market-data/tests/ -v

test-storage: ## Run storage service tests only
	python -m pytest services/storage/tests/ -v

test-alpha: ## Run alpha engine tests only
	python -m pytest services/alpha-engine/tests/ -v

test-risk: ## Run risk gateway tests only
	python -m pytest services/risk-gateway/tests/ -v

test-execution: ## Run execution service tests only
	python -m pytest services/execution/tests/ -v

test-post-trade: ## Run post-trade service tests only
	python -m pytest services/post-trade/tests/ -v

test-watch: ## Run tests in watch mode (requires pytest-watch)
	ptw -- -v --tb=short

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Stop services and remove volumes (WARNING: deletes all data)
	docker compose down -v
	@echo "All data volumes removed"

clean-images: ## Remove built images
	docker compose down --rmi local
