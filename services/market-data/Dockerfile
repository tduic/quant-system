FROM python:3.14-slim

WORKDIR /app

# Install system dependencies for confluent-kafka
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        librdkafka-dev && \
    rm -rf /var/lib/apt/lists/*

# Install shared library first (changes less frequently)
COPY lib/ /app/lib/
RUN pip install --no-cache-dir /app/lib/

# Install service dependencies
COPY services/market-data/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY services/market-data/market_data_svc/ /app/market_data_svc/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "market_data_svc.main"]
