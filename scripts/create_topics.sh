#!/bin/bash
# ==========================================================================
# Create Kafka topics for the quant trading system
# Runs as a one-shot init container in Docker Compose
# ==========================================================================

set -e

BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-kafka:29092}"

echo "Waiting for Kafka to be ready at ${BOOTSTRAP}..."
cub kafka-ready -b "${BOOTSTRAP}" 1 60

echo "Creating Kafka topics..."

# Raw market data — high volume, 7-day retention
kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic raw.trades \
  --partitions 6 \
  --replication-factor 1 \
  --config retention.ms=604800000 \
  --config cleanup.policy=delete

kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic raw.depth \
  --partitions 6 \
  --replication-factor 1 \
  --config retention.ms=259200000 \
  --config cleanup.policy=delete

# Signals — medium volume, 30-day retention
kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic signals \
  --partitions 6 \
  --replication-factor 1 \
  --config retention.ms=2592000000

# Orders — low volume, 30-day retention
kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic orders \
  --partitions 6 \
  --replication-factor 1 \
  --config retention.ms=2592000000

# Fills — low volume, 90-day retention
kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic fills \
  --partitions 6 \
  --replication-factor 1 \
  --config retention.ms=7776000000

# Risk events — low volume, 90-day retention
kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic risk.events \
  --partitions 1 \
  --replication-factor 1 \
  --config retention.ms=7776000000

# Order status updates — low volume, 90-day retention
kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic order.status \
  --partitions 6 \
  --replication-factor 1 \
  --config retention.ms=7776000000

# Audit log — append-only, 365-day retention
kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic audit.log \
  --partitions 3 \
  --replication-factor 1 \
  --config retention.ms=31536000000 \
  --config cleanup.policy=delete

# System heartbeat — minimal, 1-day retention
kafka-topics --create --if-not-exists \
  --bootstrap-server "${BOOTSTRAP}" \
  --topic system.heartbeat \
  --partitions 1 \
  --replication-factor 1 \
  --config retention.ms=86400000

echo ""
echo "=== Topic creation complete ==="
kafka-topics --list --bootstrap-server "${BOOTSTRAP}"
