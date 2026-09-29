# Tollgate Distributed Rate Limiting

Tollgate implements concurrency-safe, distributed rate limiting using Redis and an atomic Lua script. This architecture enforces rate quotas consistently across horizontally scaled gateway instances without race conditions, token over-allocation, or event-loop blocking.

---

## 1. Rate Limiting Architecture

Rate limiting is evaluated directly in the gateway request pipeline **before** any provider routing, retry orchestration, or model generation:

```
Client
  ↓
FastAPI
  ↓
API Key Authentication (Phase 1)
  ↓
Authenticated Tenant / Project / API Key Context
  ↓
Rate Limit Check (Phase 4 — Redis Token Bucket)
  ↓ [If allowed]
OpenAI-Compatible Gateway (Phase 2)
  ↓
Provider Reliability Layer / Retries & Failover (Phase 3)
  ↓
Upstream LLM Provider
```

If a client exceeds their rate limit, Tollgate rejects the request immediately with an HTTP 429 response, avoiding unnecessary upstream provider costs and latency.

---

## 2. Algorithm: Redis-Backed Token Bucket

Unlike naive `INCR`/`EXPIRE` fixed-window counters that suffer from boundary burst spikes (up to 2x limit at window edges), Tollgate uses the **Token Bucket** algorithm:

- **Burst Capacity ($B$)**: Maximum accumulated tokens available for instantaneous request bursts.
- **Refill Rate ($R$)**: Continuous token replenishment rate in tokens per second.
- **Cost ($C$)**: Number of tokens required per request (default: 1).

### Atomic Lua Script Execution
To ensure race condition immunity under concurrent requests from multiple gateway instances, the read, refill, consumption, and expiration steps execute in a single atomic Redis Lua script:

1. **State Retrieval**: Fetches current `tokens` and `last_updated` timestamp from a Redis hash (`HGET`).
2. **Dynamic Refill**:
   $$\text{elapsed} = \max(0, \text{now} - \text{last\_updated})$$
   $$\text{tokens} = \min(B, \text{tokens} + \text{elapsed} \times R)$$
3. **Capacity Evaluation**:
   - If $\text{tokens} \ge C$: Allowed ($= 1$). Tokens decremented by $C$.
   - If $\text{tokens} < C$: Rejected ($= 0$). Tokens remain unchanged.
   - Calculates $\text{retry\_after} = \frac{C - \text{tokens}}{R}$.
   - Calculates $\text{reset\_after} = \frac{B - \text{tokens}}{R}$ (time until full capacity).
4. **State Persistence**: Saves state via `HSET` and assigns a rolling TTL to prevent orphaned keys in Redis.

---

## 3. Rate Limit Scope & Key Isolation

Rate limits are strictly isolated by authenticated entity:

- **Default Scope**: `tg:ratelimit:apikey:{api_key_id}`
- **Security Guarantee**: Raw API secrets are **never** used in Redis keys. Only internal UUIDs are referenced.
- **Tenant Isolation**: Key exhaustion on Tenant A / Key 1 has zero effect on Tenant B / Key 2.

---

## 4. Response Headers & HTTP 429 Status

### Standard Headers (Returned on All Requests)
Every response (200 OK non-streaming, 200 OK SSE streaming, and 429 Too Many Requests) includes standard rate limit headers:

| Header | Description | Example |
| :--- | :--- | :---: |
| `X-RateLimit-Limit` | Burst capacity of the client's token bucket | `20` |
| `X-RateLimit-Remaining` | Remaining tokens currently available | `14` |
| `X-RateLimit-Reset` | Ceiling seconds until the bucket is completely replenished | `2` |
| `Retry-After` | *(429 only)* Ceiling seconds until at least 1 token is available | `1` |

### HTTP 429 Error Body
When rejected, Tollgate returns an OpenAI-compatible error structure:

```json
{
  "error": {
    "message": "Rate limit exceeded. Please wait before retrying.",
    "type": "rate_limit_error",
    "code": "rate_limit_exceeded"
  }
}
```

---

## 5. Redis Failure Behavior: Fail-Closed vs. Fail-Open

Upstream network partitions or Redis maintenance must not cause undefined gateway behavior. Tollgate provides explicit, configurable failure modes:

- **`TOLLGATE_RATE_LIMIT_REDIS_FAILURE_MODE=closed` (Default)**:
  - Prioritizes cost protection and upstream abuse prevention.
  - If Redis is unreachable or times out, the gateway returns HTTP 503 Service Unavailable with a standard OpenAI error structure.
- **`TOLLGATE_RATE_LIMIT_REDIS_FAILURE_MODE=open`**:
  - Prioritizes service availability.
  - If Redis fails, a warning is logged and the request proceeds through to the gateway service without blocking the client.
- **Timeout Protection**: `TOLLGATE_RATE_LIMIT_REDIS_TIMEOUT_SECONDS` (default: 1.0s) prevents slow Redis queries from stalling the gateway event loop.

---

## 6. Configuration Settings

| Environment Variable | Default | Description |
| :--- | :---: | :--- |
| `TOLLGATE_RATE_LIMIT_ENABLED` | `true` | Master toggle to enable or disable rate limiting |
| `TOLLGATE_RATE_LIMIT_REQUESTS_PER_SECOND` | `10.0` | Sustained token replenishment rate per second ($R$) |
| `TOLLGATE_RATE_LIMIT_BURST` | `20` | Maximum accumulated token bucket capacity ($B$) |
| `TOLLGATE_RATE_LIMIT_REDIS_PREFIX` | `tg:ratelimit` | Namespace prefix for Redis rate limit keys |
| `TOLLGATE_RATE_LIMIT_REDIS_TIMEOUT_SECONDS` | `1.0` | Redis command timeout ceiling before triggering failure mode |
| `TOLLGATE_RATE_LIMIT_REDIS_FAILURE_MODE` | `closed` | `closed` (reject requests) or `open` (allow requests) on Redis fault |
