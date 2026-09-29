# Tollgate Architecture & Core Components

Tollgate is an enterprise-grade multi-tenant LLM gateway engineered to solve runaway costs, budget enforcement, provider failover, and observability challenges.

```
                  +-----------------------+
                  |  Client Applications  |
                  +-----------+-----------+
                              |
                              v
                  +-----------------------+
                  | React Dashboard (3000)|
                  +-----------------------+
                              |
                              v
                  +-----------------------+
                  | FastAPI Gateway (8000)|
                  +---+---------------+---+
                      |               |
             +--------v---+       +---v--------+
             | PostgreSQL |       |   Redis    |
             | (Database) |       | (Cache/Queue|
             +------------+       +---+--------+
                                      |
                              +-------v-------+
                              | Worker Node   |
                              +---------------+
```

## System Layers

### 1. Gateway (`apps/gateway`)
FastAPI application handling incoming OpenAI-compatible requests, verifying API tokens, evaluating tenant monthly budgets, performing semantic caching lookups, and routing requests to LLM providers.

### 2. Worker (`apps/worker`)
Background worker daemon responsible for asynchronous usage log flushing, budget reconciliation, provider health check probes, and cache index warming.

### 3. Shared Core (`packages/core`)
Centralized library containing shared Pydantic configuration schemas, database connection engines, and SQLAlchemy models.

### 4. Database & Cache (`PostgreSQL` & `Redis`)
- **PostgreSQL**: Stores tenants, project budgets, usage audit logs, and provider configurations.
- **Redis**: Low-latency cache store for rate limits, active token balances, semantic embeddings, and worker queues.

### 5. Dashboard (`apps/dashboard`)
React + TypeScript frontend providing live system visibility, budget consumption charts, provider health status, and gateway configuration.
