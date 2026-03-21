FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        librdkafka-dev && \
    rm -rf /var/lib/apt/lists/*

COPY lib/ /app/lib/
RUN pip install --no-cache-dir /app/lib/

COPY services/alpha-engine/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/alpha-engine/alpha_engine_svc/ /app/alpha_engine_svc/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "alpha_engine_svc.main"]
