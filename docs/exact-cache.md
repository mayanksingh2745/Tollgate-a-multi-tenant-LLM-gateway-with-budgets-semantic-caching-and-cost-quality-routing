# Phase 7 — Exact Response Cache

## Overview

Tollgate **Phase 7** introduces a high-performance, concurrency-safe, tenant-isolated **exact-match response cache**. When incoming OpenAI-compatible chat completion requests are identical under a strict canonicalization policy, Tollgate returns previously stored responses with sub-millisecond latency without dispatching requests to upstream LLM providers.

> [!IMPORTANT]
> **Exact-Match vs. Semantic Similarity:**
> Phase 7 implements **strictly deterministic exact-match response caching**. It does **not** perform vector embeddings, cosine similarity, or fuzzy matching. Semantic similarity caching is reserved for **Phase 8**.

---

## 1. Gateway Architecture & Request Flow

To preserve correct financial and operational accounting, the Exact Response Cache is evaluated **after** authentication and distributed rate limiting, but **before** atomic budget reservation:

```text
Client
  │
  ▼
[1] Authentication (Tenant & Project context resolution)
  │
  ▼
[2] Distributed Rate Limiting (Token Bucket)
  │  (Applies to ALL requests to protect gateway throughput)
  │
  ▼
[3] Exact Cache Lookup
  ├── HIT ────────────────────────────────────────────────────────┐
  │   • Bypass Budget Reservation ($0.00 provider cost)          │
  │   • Bypass Provider Call (~0.09ms response)                  │
  │   • Bypass Provider Usage Event (No false billing)           │
  │   • Return cached OpenAI response with X-Tollgate-Cache: HIT │
  │                                                              │
  └── MISS / BYPASS                                              │
        │                                                        │
        ▼                                                        │
      [4] Multi-Scope Budget Reservation                         │
        │                                                        │
        ▼                                                        │
      [5] Provider Execution (with Retry & Fallback)             │
        │                                                        │
        ▼                                                        │
      [6] Budget Settlement & Refund                             │
        │                                                        │
        ▼                                                        │
      [7] Cache Write (Store response with TTL)                  │
        │                                                        │
        ▼                                                        │
      [8] Async Usage Event (Published to Redis Stream)          │
        │                                                        │
        ▼                                                        │
      Return Provider Response ◄─────────────────────────────────┘
```

### Key Accounting Invariants

1. **Rate Limiting Enforced on Cache Hits:** Caching reduces upstream provider load but does not grant clients uncontrolled gateway throughput. Rate limits decrement on every request.
2. **Zero Provider Budget Consumed on Cache Hits:** Since cache hits never dispatch to upstream providers, no budget reservation or settlement occurs. Clients with exhausted budgets can still retrieve cached responses safely.
3. **No Fabricated Provider Usage Events:** Cache hits emit cache hit metrics rather than publishing fake provider token consumption events to the Redis stream.

---

## 2. Deterministic Canonicalization & Cache Key Generation

Cache keys are computed using a dedicated `Canonicalizer` that normalizes generation controls while preserving message semantics:

```text
Request Context
  ├── tenant_id: UUID
  ├── project_id: UUID
  ├── provider: str (lowercased)
  ├── model: str (lowercased)
  ├── messages: List[ChatMessage] (exact order, role, content)
  └── generation controls: (temperature, top_p, max_tokens, stop, seed, penalties)
        │
        ▼
Canonical Dictionary (Normalized types, strict order preservation)
        │
        ▼
Deterministic JSON Serialization (sort_keys=True, separators=(",", ":"))
        │
        ▼
SHA-256 Digest
        │
        ▼
Redis Key: tg:cache:res:{tenant_id}:{project_id}:{generation_version}:{hash}
```

### Normalization Rules

| Field | Canonicalization Policy |
| :--- | :--- |
| **Tenant & Project** | Hex UUID string included in cache key path and hash payload. |
| **Provider & Model** | Stripped and lowercased (`"openai"`, `"gpt-4o"`). |
| **Messages Array** | Order is **strictly preserved**. `[user, assistant]` is never merged with `[assistant, user]`. |
| **Message Content** | Whitespace is **strictly preserved**. `"hello "` and `"hello"` produce different keys. |
| **Omitted vs Defaults** | Omitted fields (`None`) are distinct from explicit defaults (`temperature=0.0`). |
| **Stop Sequences** | Normalized to list of strings (e.g., `"stop": "END"` → `["stop": ["END"]]`). |
| **Seed & Penalties** | Included only when explicitly provided in request. |

---

## 3. Cacheability & Bypass Policy

Tollgate does not blindly cache every request. Requests bypass the cache under the following safety conditions:

1. **Streaming Requests (`stream=true`):** Bypassed by default. Streaming involves chunk reassembly, client disconnects, and termination semantics unsuitable for exact caching in Phase 7.
2. **Tool & Function Calls (`tools`, `tool_choice`):** Bypassed by default to prevent replaying external application side effects.
3. **Responses Exceeding Max Size:** Responses larger than `TOLLGATE_CACHE_MAX_RESPONSE_BYTES` (default: 512 KB) are returned to the client but rejected from cache storage to protect Redis memory.
4. **Global Toggle:** When `TOLLGATE_CACHE_ENABLED=false`, all cache lookups and writes are bypassed.

---

## 4. Multi-Tenant & Project Isolation

Cache keys enforce absolute tenant and project isolation:

```text
tg:cache:res:{tenant_id}:{project_id}:{version}:{sha256}
```

* **Tenant Isolation:** Tenant A can never inspect or retrieve responses generated for Tenant B, even with identical prompts and models.
* **Project Isolation:** Projects within the same tenant maintain distinct cache namespaces.
* **API Key Sharing:** Authorized API keys belonging to the same project share the exact response cache, optimizing latency across team members.
* **Prompt Privacy:** Raw prompts, API keys, and sensitive headers are never stored in Redis key names. Only the SHA-256 hash is exposed.

---

## 5. O(1) Project Cache Invalidation

Instead of expensive and blocking Redis pattern scans (`KEYS tg:cache:*`), Tollgate implements **generation-counter namespace invalidation**:

1. Each project maintains an atomic version counter in Redis:
   ```text
   tg:cache:ver:{tenant_id}:{project_id}
   ```
2. When an admin invalidates the project cache via `DELETE /api/v1/projects/{project_id}/cache`, Tollgate executes `INCR` on the version key in **O(1)** time.
3. Subsequent cache lookups for that project automatically construct cache keys using the new generation version, immediately missing prior cache entries.
4. Old cache entries expire naturally via their TTL, avoiding spikes in Redis CPU utilization.

### RBAC Authorization

Invalidation is strictly protected by Tollgate RBAC:
* Requires `owner` or `admin` role.
* Tenant isolation is validated against the database.
* Scoped API keys cannot invalidate projects outside their tenant.

---

## 6. Resilience & Fail-Open Behavior

The cache operates as a latency and cost optimization, **never** a single point of failure:

* **Redis Lookup Failure:** Caught and logged; the request fails open and proceeds directly to the provider.
* **Redis Write Failure:** Caught and logged; the client still receives the successful provider response.
* **Corrupted Payloads:** Caught during JSON deserialization; treated as a cache MISS, deleted from the backend, and routed to the provider.
* **Schema Versioning:** Cached envelopes include `cache_version = 1`. Incompatible schema versions are automatically deleted and bypassed.

---

## 7. Configuration Reference

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `TOLLGATE_CACHE_ENABLED` | `true` | Globally enable/disable exact response caching |
| `TOLLGATE_CACHE_TTL_SECONDS` | `300` | Time-to-live for cached responses (5 minutes) |
| `TOLLGATE_CACHE_MAX_RESPONSE_BYTES` | `524288` | Max response size eligible for caching (512 KB) |
| `TOLLGATE_CACHE_REDIS_PREFIX` | `tg:cache` | Redis key namespace prefix |
| `TOLLGATE_CACHE_HEADER_ENABLED` | `true` | Expose `X-Tollgate-Cache: HIT \| MISS \| BYPASS` header |

---

## 8. Observability & Telemetry

### HTTP Response Headers

When `TOLLGATE_CACHE_HEADER_ENABLED=true`, Tollgate adds:
* `X-Tollgate-Cache: HIT` — Response served directly from exact cache.
* `X-Tollgate-Cache: MISS` — Response was cacheable but not found; provider was executed and response cached.
* `X-Tollgate-Cache: BYPASS` — Request bypassed cache due to streaming, tool definitions, or configuration.

### Metrics

| Metric Name | Type | Description |
| :--- | :--- | :--- |
| `cache_hits_total` | Counter | Total successful exact cache hits |
| `cache_misses_total` | Counter | Total cache misses |
| `cache_bypasses_total` | Counter | Total requests bypassing cache |
| `cache_lookup_errors_total` | Counter | Total Redis lookup errors (failed open) |
| `cache_write_errors_total` | Counter | Total Redis write errors (failed open) |
| `cache_response_too_large_total` | Counter | Responses exceeding `cache_max_response_bytes` |
| `cache_lookup_latency_ms` | Histogram | Latency distribution of cache lookups |
| `cache_write_latency_ms` | Histogram | Latency distribution of cache writes |

---

## 9. Performance Benchmark

Empirical benchmark executed via `benchmarks/benchmark_exact_cache.py`:

* **Host Platform:** Windows 10 (AMD64), Python 3.13.2
* **Iterations:** 1,000 requests per operation
* **Test Model:** `gpt-4o` with system and user messages

| Operation | Average Latency | P50 Latency | P95 Latency | P99 Latency | Throughput |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Canonicalization & SHA-256** | 0.0209 ms | 0.019 ms | 0.035 ms | 0.052 ms | ~47,848 ops/sec |
| **Cache Miss (Cold Lookup)** | 0.0626 ms | 0.058 ms | 0.098 ms | 0.180 ms | ~15,971 req/sec |
| **Cache Write (Envelope + TTL)** | 0.1001 ms | 0.0668 ms | 0.1575 ms | 0.4148 ms | ~9,986 writes/sec |
| **Cache Hit (Warm Deserialization)**| 0.0979 ms | 0.0643 ms | 0.1646 ms | 0.3621 ms | ~10,216 req/sec |

### Round-Trip Comparison

* **Upstream LLM Provider Call:** ~450.0 ms
* **Tollgate Exact Cache Hit:** ~0.098 ms (**4,597x speedup**)
* **Provider Cost on Hit:** **$0.00 (100% cost savings)**
