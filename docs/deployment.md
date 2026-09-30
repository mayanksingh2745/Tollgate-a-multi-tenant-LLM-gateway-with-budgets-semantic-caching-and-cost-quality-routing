# Production Deployment Architecture & Guide (Phase 15A)

## 1. Target Deployment Architecture

Tollgate is architected as a modular-monolith designed for deterministic, reproducible deployment on a single VM/host or containerized infrastructure using Docker Compose.

```text
                           Internet / Client Traffic
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ NGINX Reverse Proxy & TLS │  (Port 80/443)
                        └─────────────┬─────────────┘
                                      │
           ┌──────────────────────────┴──────────────────────────┐
           │                                                     │
           ▼ (API & Web Traffic)                                 ▼ (Static Assets / SPA)
┌─────────────────────────────────┐                   ┌─────────────────────────────┐
│    Tollgate API Gateway         │                   │    React Admin Dashboard    │
│  (FastAPI ASGI, Non-Root 10001) │                   │  (Vite SPA, NGINX Alpine)   │
└──────────┬──────────────────────┘                   └─────────────────────────────┘
           │
           ├───────────────────────────────┐
           ▼ (State, Budgets, Analytics)   ▼ (Token Buckets, Caches, Usage Stream)
┌─────────────────────────────────┐   ┌─────────────────────────────┐
│    PostgreSQL 15 + pgvector     │   │      Redis 7 Cluster        │
│  (Persistent Volume, Internal)  │   │  (Persistent Volume, Auth)  │
└─────────────────────────────────┘   └──────────────┬──────────────┘
                                                     │
                                                     ▼ (XREADGROUP consumer)
                                      ┌─────────────────────────────┐
                                      │    Tollgate Usage Worker    │
                                      │  (Async Stream Processor)   │
                                      └─────────────────────────────┘

Observability Pipeline (Isolated on tollgate-backend):
  API / Worker  ──[Metrics]──▶ Prometheus (9090) ──▶ Grafana (127.0.0.1:3001)
  API / Worker  ──[Traces]───▶ Jaeger OTLP Collector (4318)
```

---

## 2. Environment Differentiation Matrix

| Dimension | Development | Staging | Production |
| :--- | :--- | :--- | :--- |
| **`ENVIRONMENT`** | `development` | `staging` | `production` |
| **`DEBUG`** | `true` | `false` | `false` |
| **CORS Origins** | Wildcard `*` | Specific test origin | Explicit production origin (`https://app.tollgate.ai`) |
| **Interactive Docs** | Enabled (`/docs`, `/redoc`) | Enabled / Auth-only | Disabled by default (`TOLLGATE_DOCS_ENABLED=false`) |
| **HSTS** | Disabled | Enabled | Enabled (`TOLLGATE_ENABLE_HSTS=true`) |
| **Database Binding** | `127.0.0.1:5432` | Internal Docker network | Internal Docker network (`tollgate-backend`) |
| **Redis Binding** | `127.0.0.1:6379` | Internal Docker network | Internal Docker network with `--requirepass` |
| **Metrics Auth** | Disabled or default token | Required | Required high-entropy secret token |
| **Container User** | Non-root (`tollgate:10001`) | Non-root (`tollgate:10001`) | Non-root (`tollgate:10001`) |
| **Image Tags** | Local build / latest | Immutable Git SHA | Immutable Git SHA (`tollgate-api:<sha>`) |

---

## 3. Capacity & Connection Sizing

### A. Database Connection Pool
* **PostgreSQL Server Default**: `max_connections = 100`
* **API Gateway Pool**:
  - `pool_size = 10`, `max_overflow = 20` (Max 30 connections per API replica)
  - At 2 replicas: $2 \times 30 = 60$ connections max.
* **Usage Worker Pool**:
  - `pool_size = 10`, `max_overflow = 10` (Max 20 connections)
* **Migrations / Admin**:
  - 5 reserved connections for Alembic and administrative maintenance.
* **Total Connection Demand**: $60 + 20 + 5 = 85$ connections (comfortably within `max_connections = 100`).

### B. Redis Connection Capacity
* **Connection Multiplexing**: Redis connections are managed via singleton connection pools in `gateway.src.redis` and `apps.worker.src.main`.
* **Zero Per-Request Connection Overhead**: Connections are retained in the pool and reused across requests.
* **Max Clients**: Redis supports 10,000 concurrent client connections by default, exceeding Tollgate's concurrency footprint by two orders of magnitude.

---

## 4. Step-by-Step Production Deployment Procedure

### Prerequisites
1. Docker Engine $\ge 24.0$ and Docker Compose V2.
2. Verified `.env` file populated with production credentials (copied from `.env.example`).
3. Domain DNS pointing to the host VM.

### Deployment Execution
Execute the automated deployment script:
```bash
export ENVIRONMENT=production
./scripts/deploy.sh
```

The script automatically executes the 7-stage deployment pipeline:
1. **Config Validation**: Checks for required production secrets and verifies that default passwords are not present.
2. **Release Identification**: Extracts the immutable Git commit SHA.
3. **Image Compilation**: Builds tagged images (`tollgate-api:<sha>`, `tollgate-worker:<sha>`, `tollgate-dashboard:<sha>`).
4. **Database Migrations**: Applies all pending Alembic schema revisions (`alembic upgrade head`).
5. **Service Recreation**: Starts container services using `docker-compose.prod.yml`.
6. **Readiness Probing**: Polls `GET /health/ready` until all subsystems (PostgreSQL, Redis) confirm health.
7. **Smoke Verification**: Executes end-to-end HTTP smoke tests against `/health/version` and `/healthz`.

---

## 5. Health Endpoints & Operational Verification

| Endpoint | Purpose | SLA / Behavior |
| :--- | :--- | :--- |
| `GET /health/live` | Process liveness probe | Returns HTTP 200 `{"status": "alive"}` instantly without external I/O. |
| `GET /health/ready` | Traffic readiness probe | Verifies active database connection, Redis connectivity, and returns 200 or 503. |
| `GET /health/version` | Release version metadata | Returns `{"service": "tollgate-api", "version": "1.0.0", "git_commit": "...", "environment": "production"}`. |
| `GET /healthz` | Legacy simple check | Returns HTTP 200 `{"status": "ok"}` with UTC timestamp. |
| `GET /metrics` | Prometheus metrics scrape | Protected by `Authorization: Bearer <METRICS_TOKEN>`. |
