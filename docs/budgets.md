# Tollgate Budget Reservation & Settlement

Tollgate implements concurrency-safe, multi-tenant budget reservation and settlement to prevent runaway LLM costs. By utilizing an atomic, two-phase reservation protocol backed by Redis Lua scripts, Tollgate guarantees that neither tenants nor projects can overspend their allocated daily or monthly spending limits, even under massive concurrent request volume.

---

## 1. Budget Architecture

Budget enforcement is executed directly in the request path **before** any upstream provider capacity is consumed:

```
Request arrives
    ↓
API Key Authentication (Phase 1)
    ↓
Distributed Rate Limiting (Phase 4)
    ↓
Estimate Maximum Request Cost
    ↓
Atomic Multi-Scope Reservation (Phase 5 — Redis Lua)
    ↓ [If budget available]
Provider Execution & Failover (Phase 2 & 3)
    ↓
Receive Actual Usage Tokens
    ↓
Atomic Budget Settlement (Phase 5 — Redis Lua)
    ├─ Commit actual cost to spent
    └─ Refund unused reservation
```

Tollgate never relies on naive "check balance then subtract later" logic. Because concurrent requests could read the same balance and concurrently overspend, budget must be reserved *before* provider execution.

---

## 2. Budget Hierarchy & Scopes

Spending controls are enforced hierarchically across two organizational layers and two temporal intervals:

```
Tenant (Daily & Monthly Budget)
 └── Project (Daily & Monthly Budget)
      └── API Keys
```

A client request must satisfy **all** configured budgets:
1. **Tenant Daily Budget** (if set)
2. **Tenant Monthly Budget** (if set)
3. **Project Daily Budget** (if set)
4. **Project Monthly Budget** (if set)

If *any* scope has insufficient remaining capacity, the reservation is rejected atomically, and the provider is never invoked.

---

## 3. Exact Money Representation

Binary floating-point types (`float`, `double`) introduce precision loss and rounding errors unacceptable in financial and billing systems.

Tollgate strictly represents all currency values in **integer microdollars**:

$$\$1.00 = 1{,}000{,}000\text{ microdollars}$$
$$\$0.001 = 1{,}000\text{ microdollars}$$

All budgets, token prices, pre-request reservations, actual costs, and refunds are calculated and stored as 64-bit integers (`int` in Python, `BigInteger` in PostgreSQL, stringified integers in Redis). Fractional microdollars are always rounded up using ceiling division to ensure budget ceilings are never breached.

---

## 4. Cost Model & Pre-Request Estimation

### Pricing Model
Token pricing is maintained per model in integer microdollars per 1,000,000 tokens:

$$\text{input\_cost} = \left\lceil \frac{\text{input\_tokens} \times \text{input\_microdollars\_per\_million}}{1{,}000{,}000} \right\rceil$$
$$\text{output\_cost} = \left\lceil \frac{\text{output\_tokens} \times \text{output\_microdollars\_per\_million}}{1{,}000{,}000} \right\rceil$$
$$\text{total\_cost} = \text{input\_cost} + \text{output\_cost}$$

### Estimation Algorithm
Before contacting the upstream provider, Tollgate computes the maximum potential cost of the completion:
1. **Input Tokens**: Estimated deterministically from prompt messages (~4 characters per token + per-message framing overhead + conversation priming).
2. **Maximum Output Tokens**: Uses request `max_tokens` if specified, or falls back to `TOLLGATE_DEFAULT_MAX_OUTPUT_TOKENS` (default: 4096).
3. **Reserved Amount**: $\text{estimated\_cost} = \text{pricing.calculate\_cost}(\text{model}, \text{prompt\_tokens}, \text{max\_output\_tokens})$.

---

## 5. Atomic Redis Reservation & Settlement Protocol

### Step 1: Reservation (`BUDGET_RESERVE_LUA`)
- Evaluates period keys (e.g., `tg:budget:tenant:{id}:d:YYYY-MM-DD`, `tg:budget:project:{id}:m:YYYY-MM`).
- Purges any expired reservation leases and restores their reserved budget.
- Checks if $\text{spent} + \text{reserved} + \text{estimated\_cost} \le \text{limit}$ across all active scopes.
- If allowed: increments `reserved` on all scopes, registers the reservation lease with TTL (`TOLLGATE_BUDGET_RESERVATION_TTL_SECONDS`), and returns `{1, "reserved", reservation_id}`.
- If rejected: modifies zero state and returns `{0, "budget_exceeded", scope}`.

### Step 2: Settlement (`BUDGET_SETTLE_LUA`)
- Upon provider completion, receives normalized token usage (`prompt_tokens`, `completion_tokens`).
- Computes exact actual cost: $\text{actual\_cost}$.
- Computes refund: $\text{refund} = \max(0, \text{estimated\_cost} - \text{actual\_cost})$.
- Decrements `reserved` by `estimated_cost` and increments `spent` by `actual_cost`.
- Marks reservation state as `settled`.
- **Idempotency Guarantee**: Calling settle twice on the same `reservation_id` is a safe no-op and will never double-charge.

### Step 3: Release on Provider Failure (`BUDGET_RELEASE_LUA`)
- If the upstream provider fails before billable tokens are generated, the reservation is released immediately.
- Decrements `reserved` by `estimated_cost` without changing `spent`.

---

## 6. Streaming & Client Disconnect Safety

- **Stream Initialization**: Budget is fully reserved before the SSE response begins.
- **Incremental Delivery**: Chunks are forwarded to the client while tracking emitted tokens.
- **Normal Completion**: Settle with actual input and output tokens consumed.
- **Client Disconnect / Mid-Stream Failure**: When a client disconnects or an upstream timeout occurs during streaming, the generator `finally` handler settles with whatever partial tokens were generated, or releases the full reservation if 0 tokens were generated.

---

## 7. Crash Recovery & Lease Expiration

If a gateway node crashes mid-flight after reserving budget:
- Every reservation has a rolling lease TTL (`TOLLGATE_BUDGET_RESERVATION_TTL_SECONDS = 120s`).
- Expired reservations are stored in an auxiliary Redis sorted set (`key:res_exp`).
- Subsequent requests on that budget scope automatically detect expired leases, decrement `reserved`, and return the locked capacity to the available pool. No orphan budget leaks can occur.

---

## 8. Budget Configuration REST APIs

Authorized administrators can configure spending limits via REST:

| Method | Endpoint | Description | Permitted Roles |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/tenants/{tenant_id}/budget` | View tenant daily & monthly spending limits | `owner`, `admin`, `viewer` |
| `PUT` | `/api/v1/tenants/{tenant_id}/budget` | Update tenant daily & monthly spending limits | `owner`, `admin` (`viewer` forbidden: 403) |
| `GET` | `/api/v1/projects/{project_id}/budget` | View project daily & monthly spending limits | `owner`, `admin`, `viewer` |
| `PUT` | `/api/v1/projects/{project_id}/budget` | Update project daily & monthly spending limits | `owner`, `admin` (`viewer` forbidden: 403) |

---

## 9. Error Responses: 402 vs. 429

Tollgate cleanly separates rate-limiting from budget limits:

- **Rate Limit Exceeded**: Returns HTTP 429 Too Many Requests (`code: "rate_limit_exceeded"`).
- **Budget Exceeded**: Returns **HTTP 402 Payment Required** (`code: "budget_exceeded"`):
  ```json
  {
    "error": {
      "message": "Budget exceeded for tg:budget:tenant:.... Insufficient spending balance.",
      "type": "budget_error",
      "code": "budget_exceeded"
    }
  }
  ```

---

## 10. Observability & Telemetry

Internal bounded-cardinality counters track budget health:
- `budget_reservations_total`
- `budget_reservation_rejections_total`
- `budget_settlements_total`
- `budget_releases_total`
- `budget_expirations_total`
- `budget_reservation_errors_total`
- `budget_settlement_errors_total`

---

## 11. Known Limitations & Future Work

- **Phase 5 Scope**: Enforces real-time synchronous budget prevention in the request path.
- **Phase 6 Scope**: Will introduce Redis Streams, asynchronous background workers, and PostgreSQL rollup tables for long-term historical analytics and dashboard visualization.
