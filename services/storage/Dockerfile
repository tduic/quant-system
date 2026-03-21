FROM python:3.14-slim

WORKDIR /app

# Install system dependencies for confluent-kafka and asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        librdkafka-dev \
        libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install shared library first
COPY lib/ /app/lib/
RUN pip install --no-cache-dir /app/lib/

# Install service dependencies
COPY services/storage/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY services/storage/storage_svc/ /app/storage_svc/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "storage_svc.main"]
