FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/packages/core/src:/app/apps/worker

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
COPY packages/core /app/packages/core
COPY apps/worker /app/apps/worker

RUN pip install --no-cache-dir -e /app/packages/core -e /app/apps/worker

CMD ["python", "apps/worker/src/main.py"]
