FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        librdkafka-dev \
        libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY lib/ /app/lib/
RUN pip install --no-cache-dir /app/lib/

COPY services/post-trade/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/post-trade/post_trade_svc/ /app/post_trade_svc/
COPY services/backtest/backtest_svc/ /app/backtest/backtest_svc/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "post_trade_svc.main"]
