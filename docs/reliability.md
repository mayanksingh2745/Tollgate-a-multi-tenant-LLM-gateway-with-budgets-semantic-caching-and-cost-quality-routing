# Tollgate Provider Reliability, Retries & Failover

Tollgate's reliability layer ensures that upstream LLM provider failures do not degrade client experiences. When upstream providers experience transient outages, network dropouts, or rate limits, Tollgate dynamically orchestrates retries with exponential backoff, respects overall request deadlines, and fails over to deterministic fallback providers.

---

## 1. Reliability Architecture

```
                ┌─ success ───────────────→ client
                │
Request → Provider A
                │
                └─ transient failure
                         ↓
                      retry
                         ↓
                  still failing
                         ↓
                     fallback
                         ↓
                    Provider B
                         ↓
                      success
                         ↓
                      client
```

Tollgate separates routing, reliability execution, and provider transport into distinct architectural layers:

1. **Client / API Layer**: Receives standard OpenAI-compatible requests and validates tenant authentication.
2. **Gateway Service**: Resolves the logical model to a configured primary provider and deterministic fallback routes.
3. **Reliability Layer (`ReliableExecutor`)**:
   - Manages retry attempts, overall request timeouts, backoff, jitter, and Retry-After constraints.
   - Evaluates provider health state and cooldowns.
   - Evaluates whether failures are retryable and/or eligible for fallback.
4. **Provider Adapters**: Translate normalized Tollgate requests to upstream provider formats and normalize errors without embedding provider-specific retry loops.

---

## 2. Failure Classification System

Tollgate classifies all provider errors into standardized categories using a centralized classifier (`gateway.src.reliability.failure_classifier`):

| Failure Category | Examples | Retryable? | Fallback Eligible? | Notes |
| :--- | :--- | :---: | :---: | :--- |
| `TRANSIENT` | Network drops, connection resets, HTTP 500, 502, 503, timeouts | **Yes** | **Yes** | Retried with backoff; falls back if attempts exhausted. |
| `RATE_LIMITED` | HTTP 429 | **Yes** | **Yes** | Retried respecting `Retry-After` header when present. |
| `AUTHENTICATION_FAILURE` | HTTP 401, invalid provider API key | **No** | **Yes** | Re-attempting same credentials won't help; can fail over to another provider. |
| `BAD_REQUEST` | HTTP 400, invalid parameters, unsupported options | **No** | **No** | The client request itself is invalid; failing over sends the same bad payload. |
| `NOT_FOUND` | HTTP 404, model not found upstream | **No** | **Yes** | Model unavailable at provider; fallback provider may support target logical model. |
| `CONTENT_POLICY` | Provider content moderation violation | **No** | **No** | Do not blindly replay blocked content across providers. |
| `INTERNAL` | Unexpected internal gateway faults | **No** | **No** | Gateway-side error; should be corrected internally. |

---

## 3. Retry Policy & Bounds

Tollgate enforces bounded retries:

- **`max_attempts`**: Bounded total attempts **including** the initial attempt (e.g., `max_attempts = 3` means 1 initial call + at most 2 retries, NOT 1 initial + 3 retries).
- **Default Setting**: 3 attempts (configurable via `TOLLGATE_MAX_RETRIES`).
- **Retry Budget**: Once the attempt budget for a provider target is exhausted without success, Tollgate stops retrying that provider and checks for configured fallback providers.

---

## 4. Exponential Backoff & Jitter

### Algorithm
Delays between retries are calculated using exponential backoff:

$$\text{delay} = \min\left(\text{max\_delay},\; \text{base\_delay} \times 2^{(\text{attempt} - 1)}\right)$$

Example progression (`base_delay = 0.25s`, `max_delay = 5.0s`):
- Attempt 1 failure $\rightarrow 0.25\text{s}$
- Attempt 2 failure $\rightarrow 0.50\text{s}$
- Attempt 3 failure $\rightarrow 1.00\text{s}$

### Jitter Strategy
To avoid "thundering herd" problems where many synchronized requests hammer a recovering provider simultaneously, Tollgate applies bounded uniform random jitter:

$$\text{delay\_with\_jitter} = \text{delay} \times \left(1 + \text{random}(0.0, 0.5)\right)$$

The random jitter is bounded, ensuring predictable maximum retry wait times while spreading out provider load.

### Asynchronous Execution
Retry waits utilize non-blocking `asyncio.sleep()`. The FastAPI event loop is never blocked by synchronous sleep calls.

---

## 5. Overall Request Deadlines & Timeouts

Tollgate implements both per-provider attempt timeouts and an overall request deadline:

- **`TOLLGATE_PROVIDER_TIMEOUT_SECONDS`** (default: 30s): Maximum time allowed for an individual HTTP call to an upstream provider.
- **`TOLLGATE_REQUEST_TIMEOUT_SECONDS`** (default: 60s): Overall time budget for the entire request across all retries and fallback attempts.

### Deadline Enforcement
Before each retry and each fallback attempt, Tollgate computes:

$$\text{remaining\_time} = \text{request\_deadline} - \text{current\_time}$$

If $\text{remaining\_time} \le 0$ or if the calculated backoff delay exceeds remaining time, retries cease immediately and Tollgate returns a timeout error to the client, preventing unbounded execution.

---

## 6. Provider Retry-After Handling

When an upstream provider responds with HTTP 429 and includes a `Retry-After` header:

1. Tollgate parses the header (supports integer seconds).
2. Clamps the delay between `base_delay` and `max_delay` (`TOLLGATE_RETRY_MAX_DELAY`).
3. Verifies that the requested wait fits within the remaining overall request deadline.
4. If the delay exceeds the remaining deadline, Tollgate immediately moves to an available fallback provider rather than sleeping past the deadline.

---

## 7. Deterministic Fallback Chains

Fallback routes are registered per logical model:

```python
FallbackRoute(
    logical_model="gpt-4o",
    primary=ProviderTarget(provider_name="openai", upstream_model="gpt-4o"),
    fallbacks=[
        ProviderTarget(provider_name="azure-openai", upstream_model="gpt-4o-eastus"),
        ProviderTarget(provider_name="anthropic", upstream_model="claude-3-5-sonnet-20241022"),
    ],
)
```

### Fallback Execution Rules
- Fallback occurs **only** when the failure category is fallback-eligible (`TRANSIENT`, `RATE_LIMITED`, `AUTHENTICATION_FAILURE`, `NOT_FOUND`).
- Client-side validation errors (`BAD_REQUEST`, `CONTENT_POLICY`) **never** trigger fallback.
- Fallbacks are attempted in the exact configured sequence.

---

## 8. Streaming Failure Handling

Streaming responses require strict guarantees to avoid corrupting client state:

### Case A: Failure BEFORE First Chunk Sent
- If the upstream provider fails before any meaningful data chunk has been emitted to the client stream, Tollgate can safely retry the primary provider or fail over to a fallback provider.

### Case B: Failure AFTER Chunks Have Been Sent
- Once at least one data chunk has been delivered downstream to the client, Tollgate **never** silently restarts the request with another provider.
- Restarting mid-stream would cause duplicate tokens, mismatched message sequences, or disjoint completions.
- The stream terminates immediately and safely logs the provider failure.

---

## 9. Provider Health State & Recovery

Tollgate maintains a lightweight in-memory health tracker (`ProviderHealthTracker`):

- **Health Status**: Providers start `HEALTHY`.
- **Threshold**: After consecutive failures exceed `failure_threshold` (default: 3), the provider is marked `TEMPORARILY_UNAVAILABLE`.
- **Cooldown**: The provider remains unavailable for `cooldown_seconds` (default: 30s). Subsequent requests skip the degraded provider and proceed directly to healthy fallback targets.
- **Probe & Recovery**: Once the cooldown expires, the next request acts as a controlled probe. A successful request restores the provider to `HEALTHY`; a failed request resets the cooldown.

*(Note: This in-memory tracker provides lightweight per-instance health. Phase 10 will introduce distributed circuit breakers across gateway clusters).*

---

## 10. Instrumentation & Failure Metrics

Internal counters track provider health and execution without requiring external monitoring agents:

- `provider_requests_total{provider, model}`
- `provider_failures_total{provider, failure_category}`
- `provider_retries_total{provider}`
- `provider_fallbacks_total{from_provider, to_provider}`
- `provider_timeouts_total{provider}`
- `provider_attempt_latency{provider}`

Security Guarantee: Logs and metrics never record credentials, API keys, `Authorization` headers, prompts, or completions.

---

## 11. Important Design Tradeoffs

### Why Retry?
Transient network hiccups and momentary 5xx spikes are common in distributed cloud APIs. Retrying automatically prevents transient failures from disrupting user sessions.

### Why Not Retry Everything?
- Retrying non-retryable errors (e.g. 400 Bad Request) increases costs and latency while providing zero chance of success.
- Retrying rate-limited requests aggressively creates amplification spirals that worsen outages.

### Why Exponential Backoff?
Fixed delays cause synchronized bursts against recovering providers. Exponential backoff increases the spacing between retries exponentially, giving upstream services breathing room to recover.

### Why Jitter?
When hundreds of concurrent requests fail at the same moment, deterministic exponential backoff would cause all of them to retry at the exact same millisecond. Jitter randomizes intervals to smooth traffic distribution.

### Why Fallback?
Provider outages (e.g. major cloud region down) can last minutes or hours. Retrying the same provider during an outage is futile; routing to a secondary provider restores service immediately.

### Why Not Fallback on HTTP 400?
A 400 Bad Request indicates malformed JSON, invalid parameters, or an invalid message array. Forwarding the same bad payload to a fallback provider will fail identically.

### Why Not Restart a Partial Stream?
If 20 tokens were already streamed to the client UI, restarting from token 0 with a fallback provider would output doubled text or contradictory content. Safe termination is always preferable to corrupting client application state.
