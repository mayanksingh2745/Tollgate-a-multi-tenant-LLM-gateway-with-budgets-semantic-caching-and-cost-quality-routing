FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/packages/core/src:/app/apps/gateway

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
COPY packages/core /app/packages/core
COPY apps/gateway /app/apps/gateway

RUN pip install --no-cache-dir -e /app/packages/core -e /app/apps/gateway

EXPOSE 8000

CMD ["uvicorn", "gateway.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
