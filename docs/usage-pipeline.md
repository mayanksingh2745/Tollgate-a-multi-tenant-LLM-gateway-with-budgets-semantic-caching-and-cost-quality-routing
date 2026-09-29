# Usage Pipeline & Cost Accounting

This document details the architecture, stream semantics, consumer worker lifecycle, database models, idempotency safeguards, and delivery guarantees of Tollgate's **asynchronous usage-event pipeline**.

---

## 1. Architectural Overview

Tollgate separates the latency-critical request path from usage persistence. Writing usage and rollup records directly to PostgreSQL inside the gateway request loop introduces database connection contention, locks, and tail latency spikes.

Instead, Tollgate adopts an **asynchronous, durable usage-event pipeline**:

```text
Client Request
      ↓
API Key Authentication
      ↓
Distributed Rate Limiting (Token Bucket)
      ↓
Atomic Budget Reservation (Redis Lua)
      ↓
Upstream Provider Execution
      ↓
Response Completion / Settlement
      │
      ├───────────────────────────────┐
      ↓                               ↓
Client Response                 Usage Event
                              (XADD tg:usage:events)
                                      ↓
                                Redis Stream
                                      ↓
                          Consumer Group: tg-usage-workers
                           ┌──────────┼──────────┐
                           ↓          ↓          ↓
                         Worker 1   Worker 2   Worker 3
                           │          │          │
                           └──────────┼──────────┘
                                      ↓
                         Atomic PostgreSQL Transaction
                           ├─ INSERT usage_events (ON CONFLICT DO NOTHING)
                           ├─ UPSERT usage_daily_rollups
                           └─ UPSERT usage_monthly_rollups
                                      ↓
                             XACK Redis Stream
```

---

## 2. Redis Stream & Consumer Group Design

### Stream Name
`tg:usage:events`

### Consumer Group
`tg-usage-workers`

### Worker Consumer Identity
`usage-worker-<unique-id>` (e.g., `usage-worker-a1b2c3d4`)

### Why Redis Streams?
- **Durability**: Unlike Redis Pub/Sub, Redis Streams persist messages to disk according to Redis AOF/RDB configuration.
- **Consumer Groups & PEL**: Supports multiple worker replicas sharing the stream workload without duplicate delivery under normal conditions.
- **Pending Entries List (PEL)**: Messages delivered to a consumer remain tracked until explicitly acknowledged via `XACK`.
- **Fault Recovery**: Unacknowledged messages from crashed workers can be reclaimed via `XAUTOCLAIM` / `XCLAIM`.

---

## 3. Versioned Event Schema

Every event is strictly validated using Pydantic before publication and upon consumption.

```json
{
  "event_version": 1,
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "request_id": "req_8f1b62a93b484511",
  "reservation_id": "res_8f1b62a93b484511",
  "timestamp": "2026-09-30T12:00:00Z",

  "tenant_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "project_id": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
  "api_key_id": "4b6c3d9a-1c8e-4a6f-9e7b-8c5d2e3f1a0b",

  "provider": "openai",
  "model": "gpt-4o",

  "stream": false,
  "status": "success",

  "input_tokens": 1200,
  "output_tokens": 400,
  "total_tokens": 1600,

  "estimated_cost": 25000,
  "actual_cost": 18500,

  "latency_ms": 782.4,
  "attempt_count": 1,
  "fallback_used": false
}
```

### Event Versioning
- Initial version is `1`.
- If a worker receives an unsupported version (`event_version != 1`), the event is rejected and quarantined into the dead-letter stream. Unsupported versions are never silently coerced.

### Event Scope
- Terminal outcomes with usage: `success`, `provider_failure`, `client_cancelled` (when upstream tokens were consumed).
- Requests rejected *prior* to provider execution (such as invalid API key `401`, rate limit `429`, or budget exhausted `402`) do **not** generate LLM usage events, preventing fake zero-cost clutter.

---

## 4. Cost Accounting & Budget Reconciliation

1. **Integer Microdollars**: All monetary amounts are stored in integer microdollars (`$1.00 = 1,000,000 microdollars`), preventing IEEE 754 floating-point rounding errors.
2. **Estimated vs. Actual Cost**: Both `estimated_cost` (from the Phase 5 pre-request reservation) and `actual_cost` (calculated from verified provider token usage) are preserved on the event.
3. **Budget Correlation**: The event carries `reservation_id`, bridging Phase 5 atomic reservation and settlement with Phase 6 durable event accounting.

---

## 5. PostgreSQL Persistence & Rollups

### Tables

1. **`usage_events`**: Detailed record for every individual completion request.
   - Primary Key: `id` (UUID)
   - Unique Constraint: `event_id` (`UNIQUE(event_id)`)
   - Composite Indexes: `(tenant_id, created_at)`, `(project_id, created_at)`, `(model, created_at)`, `(provider, created_at)`, `request_id`.

2. **`usage_daily_rollups`**: Aggregated daily stats partitioned by dimensions.
   - Unique Constraint: `(date, tenant_id, project_id, provider, model)`
   - Aggregated Fields: `request_count`, `success_count`, `failure_count`, `input_tokens`, `output_tokens`, `total_tokens`, `estimated_cost`, `actual_cost`.

3. **`usage_monthly_rollups`**: Aggregated monthly stats partitioned by dimensions.
   - Unique Constraint: `(month, tenant_id, project_id, provider, model)`
   - Same rollup dimensions and metrics.

### Idempotency Strategy
Message redelivery can occur when a worker crashes before sending `XACK` or during `XAUTOCLAIM` reclaims.

To guarantee **effectively-once persistence**:

```sql
BEGIN;

INSERT INTO usage_events (
    id, event_id, event_version, request_id, reservation_id,
    tenant_id, project_id, api_key_id, provider, model,
    stream, status, input_tokens, output_tokens, total_tokens,
    estimated_cost, actual_cost, latency_ms, attempt_count,
    fallback_used, created_at, processed_at
) VALUES (...)
ON CONFLICT (event_id) DO NOTHING
RETURNING id;

-- Only update rollups if the row was actually inserted!
IF inserted_id IS NOT NULL THEN
    -- Upsert daily rollup
    INSERT INTO usage_daily_rollups (...)
    ON CONFLICT (date, tenant_id, project_id, provider, model)
    DO UPDATE SET
        request_count = usage_daily_rollups.request_count + 1,
        ...;

    -- Upsert monthly rollup
    INSERT INTO usage_monthly_rollups (...)
    ON CONFLICT (month, tenant_id, project_id, provider, model)
    DO UPDATE SET
        request_count = usage_monthly_rollups.request_count + 1,
        ...;
END IF;

COMMIT;
```

If `inserted_id` is null (indicating a duplicate delivery), the worker skips rollup updates and proceeds to `XACK` the message. This guarantees rollups never double-count duplicate events.

---

## 6. Worker Crash Recovery & Reclaim Behavior

1. **Pending Entry Recovery**: If a worker crashes while processing a batch, its claimed messages remain in the PEL.
2. **Visibility Timeout**: Configured via `TOLLGATE_USAGE_CLAIM_IDLE_SECONDS` (default: 60s).
3. **Autoclaim Loop**: Workers periodically execute `XAUTOCLAIM` (or `XPENDING_RANGE` + `XCLAIM` on legacy Redis) to reclaim messages idle longer than the threshold.
4. **Ordering of Acks**: A message is acknowledged via `XACK` **only after** PostgreSQL successfully commits the transaction. If PostgreSQL fails, `XACK` is omitted, leaving the message pending for bounded retry or reclaim.

---

## 7. Dead-Letter Stream

Unprocessable messages (corrupted JSON, invalid fields, unsupported schema versions) must not block the worker pipeline.

- **Stream Name**: `tg:usage:dead-letter`
- **Payload**:
  - `original_event_id`: UUID if parseable
  - `failure_reason`: Descriptive error message
  - `failure_type`: Classification (`validation_error`, `unsupported_version`)
  - `timestamp`: UTC timestamp
  - `original_payload`: Sanitized payload excerpt (headers, API keys, and prompt texts are stripped)
- After writing to the dead-letter stream, the worker acknowledges (`XACK`) the malformed message from `tg:usage:events` to unblock progress.

---

## 8. Query API & Tenant Isolation

Tollgate exposes paginated, tenant-isolated REST endpoints for usage analytics:

### Endpoints
- `GET /api/v1/usage` — Paginated list of usage events
- `GET /api/v1/usage/rollups/daily` — Aggregated daily rollups
- `GET /api/v1/usage/rollups/monthly` — Aggregated monthly rollups

### Tenant Isolation
- Requests require a valid API key (`Bearer tg_live_...`).
- Queries are strictly scoped to `ctx.tenant_id`. Any query attempting to specify a different `tenant_id` is rejected with `HTTP 403 Forbidden`.
- If an API key is scoped to a specific `project_id`, cross-project queries within the tenant are also rejected with `HTTP 403 Forbidden`.

### Cursor Pagination
`GET /api/v1/usage` supports opaque base64 cursor pagination (`limit` + `cursor`), ensuring stable results across live inserts:
```json
{
  "items": [...],
  "next_cursor": "MjAyNi0wOS0zMFQxMjowMDowMHwwZWI5MWUwMy0xOGIxLTRlMTktYmFmNS1mY2JhNzMwY2U1NjM=",
  "has_more": true
}
```

---

## 9. Delivery Guarantees & Consistency Boundaries

- **Message Broker Delivery**: **At-least-once**. Redis Streams and consumer groups guarantee that every published message is delivered to a consumer and will be redelivered/reclaimed if not acknowledged.
- **Persistence Guarantee**: **Effectively-once**. Database-level unique constraints (`UNIQUE(event_id)`) and idempotent rollup upserts ensure that duplicate deliveries do not duplicate records or inflate aggregations.
- **Consistency Boundary**: Event publication occurs immediately following provider settlement. If the gateway process crashes after provider completion but before `XADD`, the settlement remains recorded in Redis, but the analytical usage event was not published. To mitigate this, `UsagePublisher` employs bounded retries with exponential backoff on publication.
