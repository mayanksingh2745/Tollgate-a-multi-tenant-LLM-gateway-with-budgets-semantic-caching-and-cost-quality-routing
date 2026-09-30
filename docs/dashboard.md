# Tollgate Dashboard & Tenant Analytics

## 1. Architecture

The Tollgate Dashboard provides a real-time, tenant-isolated operational control plane and telemetry interface for the Tollgate LLM Gateway. It bridges backend accounting pipelines (usage events, exact cache counters, semantic cache vectors, atomic budgets, and router evaluation metadata) into a developer-infrastructure dashboard.

### Architectural Invariant & Isolation
The dashboard operates strictly as a read/management interface and is decoupled from the critical inference path. LLM chat completions and proxy routing NEVER depend on dashboard availability:

```text
                  ┌──────────────────────┐
                  │   React Dashboard    │ (Vite + TypeScript)
                  └──────────┬───────────┘
                             │ Authenticated Bearer Token / Session
                             ↓
                    Dashboard API Router (/api/v1/dashboard/*)
                             │
                   ┌─────────┴─────────┐
                   ↓                   ↓
             PostgreSQL Aggregation   Auth / RBAC Verification
             (Dialect-aware SUM/AVG)  (Tenant & Project Isolation)
                   │
          ┌────────┴─────────┐
          ↓                  ↓
     Usage / Rollups       Budgets (Atomic microdollars)
          │
     ┌────┴─────┬──────────┬───────────┐
     ↓          ↓          ↓           ↓
   Models    Providers    Cache       Router
```

---

## 2. Frontend Structure

The frontend application resides in `apps/dashboard/` and is built using React 18, TypeScript, and Vite 5, adhering to a modular, component-driven design:

```text
apps/dashboard/
├── src/
│   ├── api/
│   │   └── client.ts            # Typed TollgateApiClient with bearer token management
│   ├── components/
│   │   ├── charts/
│   │   │   ├── AreaChart.tsx    # SVG gradient line/area chart with hover tooltips
│   │   │   ├── BarChart.tsx     # Normalized horizontal comparative bar chart
│   │   │   └── DonutChart.tsx   # SVG ring chart with central metric readout
│   │   ├── Header.tsx           # App header, project selector, time-range toggle, logout
│   │   ├── MetricCard.tsx       # Reusable KPI metric card with loading skeletons
│   │   ├── RequestDetailModal.tsx # Request telemetry modal (safe metadata only)
│   │   └── Sidebar.tsx          # Navigation sidebar with tenant context and role badge
│   ├── pages/
│   │   ├── OverviewPage.tsx     # High-level KPIs, request/cost volume, routing split
│   │   ├── UsagePage.tsx        # Dynamic time-series (Requests, Tokens, Cost)
│   │   ├── CostsBudgetsPage.tsx # Multi-dimensional cost breakdown & budget gauges
│   │   ├── ModelsPage.tsx       # Throughput, token breakdown, latency, & model error rates
│   │   ├── ProvidersPage.tsx    # Upstream reliability, retry/fallback rates, & p50/p95 latency
│   │   ├── CachePage.tsx        # Exact vs semantic cache hits, hit rates, cost avoided
│   │   ├── RouterPage.tsx       # Production router splits vs offline benchmark evaluations
│   │   ├── RequestsPage.tsx     # Server-side paginated request explorer with filters/sorting
│   │   ├── SettingsPage.tsx     # Project listing and API key management (metadata only)
│   │   └── LoginPage.tsx        # Dual-mode authentication (Email/Password or API Key)
│   ├── types/
│   │   └── dashboard.ts         # TypeScript schema definitions matching backend responses
│   ├── __tests__/               # Vitest unit test suites (Charts, Metrics, Nav, Login)
│   ├── App.tsx                  # Root application shell with authentication state machine
│   ├── App.css                  # Production developer dark-mode aesthetic styling
│   └── main.tsx                 # Entrypoint
├── Dockerfile                   # Multi-stage production container build (Vite + Nginx)
├── nginx.conf                   # Reverse proxy configuration with security headers
└── package.json
```

---

## 3. Backend Dashboard APIs

All endpoints are registered under `/api/v1/dashboard/` and require valid Bearer token authentication:

| Method | Endpoint | Description | Permitted Roles |
|---|---|---|---|
| `GET` | `/api/v1/dashboard/overview` | High-level summary KPIs (requests, tokens, cost, cache, router) | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/usage` | Time-series aggregation buckets (hour/day) | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/costs` | Multi-dimensional cost breakdown (by model, provider, project) | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/budgets` | Atomic budget status, spent microdollars, utilization percentage | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/models` | Per-model usage, input/output tokens, cost, latency, error rate | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/providers` | Upstream provider reliability, retries, fallbacks, latency | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/cache` | Exact vs semantic cache performance, hit rates, estimated savings | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/router` | Router decisions (cheap vs strong), fallback rate, offline benchmark | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/requests` | Server-side paginated, filterable, and sortable requests table | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/dashboard/requests/{id}` | Detailed telemetry and routing metadata for a single request | `owner`, `admin`, `viewer` |
| `GET` | `/api/v1/auth/me` | Current authenticated user profile, tenant identity, and projects | `owner`, `admin`, `viewer` |
| `POST` | `/api/v1/auth/login` | Email/password credential verification returning active token | Public |

---

## 4. Authorization & RBAC

The dashboard reuses Tollgate's Phase 1 Role-Based Access Control (`owner`, `admin`, `viewer`):

1. **Role Privileges**:
   - `owner`: Full visibility across tenant, projects, API key generation, revocation, and budget configuration.
   - `admin`: Full analytics visibility across tenant and assigned projects, key management, and routing telemetry.
   - `viewer`: Read-only operational visibility. Can view analytics for authorized projects. Cannot create or revoke keys, modify budgets, or alter tenant settings.
2. **Tenant Scoping**:
   - The user's `tenant_id` is extracted strictly from the cryptographic/database session or verified Bearer token.
   - All SQL queries explicitly append `WHERE tenant_id = :tenant_id`. No query parameter can override tenant scoping.
3. **Project Scoping**:
   - `owner` and `admin` users can query the entire tenant (`project_id=None`) or filter to a specific project.
   - `viewer` users are restricted server-side to their assigned `project_id`. Attempting to query another project yields HTTP 403 Forbidden.

---

## 5. Analytics Data Sources

Dashboard metrics are synthesized from four authoritative backend subsystems:

1. **`usage_events` (PostgreSQL)**:
   - Primary source for request counts, token consumption (`prompt_tokens`, `completion_tokens`), cost (`cost_microdollars`), latency (`latency_ms`), status codes, provider errors, and fallback execution.
2. **`exact_cache` (Redis Counters + In-Memory)**:
   - Increments tenant-isolated counters (`tg:cache:tenant:{tenant_id}:hits` and misses) on cache hits.
   - Guaranteed: Exact cache hits NEVER emit artificial provider usage events, preserving billing accuracy.
3. **`semantic_cache_entries` (PostgreSQL + pgvector)**:
   - Tracks persistent semantic cache entries, vector embeddings, similarity thresholds, and individual entry `hit_count` values.
4. **`budgets` (PostgreSQL)**:
   - Authoritative source for atomic reservations, current spend (`current_spend_microdollars`), and monthly limits.

---

## 6. Rollup Strategy & Mathematical Correctness

To deliver sub-50ms analytics without unbounded memory consumption:
- All metrics are calculated via PostgreSQL database aggregation (`COUNT`, `SUM`, `AVG`, `FILTER`) rather than streaming raw rows into application memory.
- For time-series queries, timestamps are bucketed using `date_trunc('hour', ...)` or `date_trunc('day', ...)` depending on the requested time range (`24h`, `7d`, `30d`).
- Dialect compatibility is maintained across SQLite (development/testing) and PostgreSQL (production) via dynamic date-truncation expressions.
- **No Double Counting**: In-flight usage events processed via the Phase 6 asynchronous worker are committed idempotently using UUID primary keys.

---

## 7. Request Explorer

The Requests Explorer allows engineers to audit LLM gateway traffic while maintaining strict enterprise privacy:

- **Server-Side Pagination**: Queries support `page` and `page_size` (enforcing a maximum of 100 items per page).
- **Filtering**: Supports project, provider, status (`success` vs `error`), cache status (`exact_hit`, `semantic_hit`, `miss`), and router decision (`cheap`, `strong`).
- **Safe Sorting**: Column sorting is strictly whitelisted (`timestamp`, `cost`, `latency`, `tokens`). Arbitrary column interpolation is blocked.
- **Privacy Guarantee**: Raw prompt text and model response payloads are NOT stored or displayed. Only operational metadata (token counts, latency, status code, provider, routing decision) is accessible.

---

## 8. Cache Analytics

The cache analytics subsystem distinguishes gateway request volume from upstream provider calls:

- **Exact Cache vs Semantic Cache**:
  - Compares exact lookup hits against similarity-based semantic hits.
  - Overall Cache Hit Rate: `(exact_hits + semantic_hits) / total_gateway_requests`.
- **Cost Avoidance**:
  - Estimates monetary savings based on token usage saved by serving cached completions rather than executing upstream provider calls.
- **Health & Reliability**:
  - Tracks cache error rates, lookup errors, and semantic threshold compliance.

---

## 9. Router Analytics

The model router view provides transparency into dynamic cost-quality routing:

1. **Production Routing Telemetry**:
   - Split between Cheap Model selections and Strong Model selections.
   - Fallback Rate: Tracks when a cheap model fails upstream and the gateway executes an automatic Phase 3 fallback to the strong model.
   - Distinction between Router Decision (e.g., cheap) and Actual Executed Model (e.g., strong due to fallback).
2. **Offline Evaluation Separation**:
   - Distinctly presents offline evaluation benchmark metrics (e.g., GSM8K evaluation dataset, quality score, cost reduction vs baseline) from live production traffic, preventing benchmark contamination of operational billing.

---

## 10. Budget Analytics

- **Source of Truth**: Sourced directly from Phase 5 atomic budget quotas in PostgreSQL.
- **Monetary Units**: Expressed internally as integer microdollars (`$1.00 = 1,000,000 microdollars`) to prevent floating-point rounding errors.
- **Utilization Tracking**:
  - Visual indicators render percentage utilization for monthly and daily budgets.
  - Clear breakdown of reserved vs settled funds.

---

## 11. Performance Considerations & Database Indexes

To guarantee fast queries as `usage_events` scales to millions of records, migration `0006_phase10_dashboard_analytics.py` adds targeted composite indexes:

- `ix_usage_events_dashboard_overview`: `(tenant_id, created_at)`
- `ix_usage_events_dashboard_project`: `(tenant_id, project_id, created_at)`
- `ix_usage_events_dashboard_provider`: `(tenant_id, provider, created_at)`
- `ix_usage_events_dashboard_model`: `(tenant_id, model, created_at)`
- `ix_usage_events_dashboard_status`: `(tenant_id, status_code, created_at)`
- `ix_usage_events_dashboard_cache`: `(tenant_id, cache_status, created_at)`

---

## 12. Security & Hardening

1. **No Sensitive Leakage**:
   - Raw API key secrets are hashed using Argon2id and never returned in dashboard responses. Only key prefixes (e.g., `tg_live_3f8...`) and metadata are shown.
   - Upstream provider credentials and authorization headers are never exposed.
2. **Strict Multi-Tenancy**:
   - Every database query binds `tenant_id` server-side from authentication tokens.
   - Cross-tenant access is tested and rejected with 401/403/404.
3. **Frontend Security**:
   - Production Docker image serves the SPA via Nginx with hardened HTTP headers (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy`).

---

## 13. Limitations & Out-of-Scope

- **Prometheus / Grafana**: This phase does not replace external infrastructure monitoring (Prometheus scrapers or Grafana dashboards). It provides tenant-specific business and operational analytics.
- **Arbitrary SQL / Ad-hoc Reports**: No unvalidated arbitrary querying or report builders are exposed.
- **Raw Prompt Search**: Full-text search over raw prompt text is deliberately excluded to protect user data privacy.
- **Forecasting & Auto-Scaling**: Predictive budgeting and autonomous router retraining are reserved for future phases.
