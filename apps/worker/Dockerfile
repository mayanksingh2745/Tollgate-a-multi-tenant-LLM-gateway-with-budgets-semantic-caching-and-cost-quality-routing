FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/packages/core/src:/app/apps/worker

# Install minimal OS dependencies and clean up cache in same layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user and group
RUN groupadd -g 10001 tollgate && \
    useradd -u 10001 -g tollgate -d /app -s /sbin/nologin tollgate

COPY pyproject.toml /app/
COPY packages/core /app/packages/core
COPY apps/worker /app/apps/worker

RUN pip install --no-cache-dir -e /app/packages/core -e /app/apps/worker && \
    chown -R tollgate:tollgate /app

# Switch to non-root runtime user
USER tollgate

CMD ["python", "apps/worker/src/main.py"]
