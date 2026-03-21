FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        librdkafka-dev && \
    rm -rf /var/lib/apt/lists/*

COPY lib/ /app/lib/
RUN pip install --no-cache-dir /app/lib/

COPY services/risk-gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/risk-gateway/risk_gateway_svc/ /app/risk_gateway_svc/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "risk_gateway_svc.main"]
