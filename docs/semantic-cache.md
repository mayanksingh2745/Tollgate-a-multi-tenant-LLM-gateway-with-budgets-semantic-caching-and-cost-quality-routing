# Phase 8 — Semantic Response Cache

## Overview

Tollgate **Phase 8** introduces a conservative, tenant-isolated, production-oriented **semantic response cache**. While Phase 7's exact-match cache returns stored responses when request payloads are character-for-character identical, the semantic response cache recognizes requests that are *semantically equivalent in intent* and safely reuses previously generated responses.

> [!CRITICAL]
> **Core Safety Principle:**
> High embedding vector similarity $\ne$ semantic equivalence.
> A semantic cache hit requires strict compatibility validation across tenant, project, provider, model, generation configuration, response format, and tool constraints. Nearest-neighbor vector proximity is merely a candidate filter, never sufficient proof of equivalence on its own.

---

## 1. Gateway Architecture & Request Flow

The tiered cache evaluation order is designed to optimize latency, avoid redundant compute, and ensure strict financial integrity:

```text
Client
  │
  ▼
[1] Authentication (Tenant & Project context resolution)
  │
  ▼
[2] Distributed Rate Limiting (Token Bucket)
  │ (Protects gateway throughput regardless of cache hit status)
  │
  ▼
[3] Tier 1: Exact Cache Lookup (Redis SHA-256 hash, ~0.05ms)
  ├── HIT ──────────────────────────────────────────────────────────────┐
  │   • Sub-millisecond response (~0.05ms)                              │
  │   • Zero embedding overhead                                         │
  │   • Zero budget reservation ($0.00)                                 │
  │   • Return cached response (X-Tollgate-Cache: HIT)                  │
  │                                                                     │
  └── MISS / BYPASS                                                     │
        │                                                               │
        ▼                                                               │
      [4] Tier 2: Semantic Cache Lookup (PostgreSQL + pgvector, ~37ms)  │
        ├── Semantic Bypass Check (streaming, tools, n > 1)             │
        ├── Generate normalized query embedding                         │
        ├── pgvector top-k nearest candidate search (cosine distance)   │
        ├── Strict compatibility & threshold filtering                  │
        ├── Dereference & validate response from Redis                  │
        │                                                               │
        ├── HIT ────────────────────────────────────────────────────────┤
        │   • Fast vector response (~37ms vs ~800ms provider latency)   │
        │   • Zero budget reservation ($0.00)                           │
        │   • Zero provider usage events                                │
        │   • Return cached response (X-Tollgate-Cache: SEMANTIC_HIT)   │
        │                                                               │
        └── MISS / SHADOW / FAILURE (Fail-Open)                         │
              │                                                         │
              ▼                                                         │
            [5] Tier 3: Multi-Scope Budget Reservation                  │
              │                                                         │
              ▼                                                         │
            [6] Upstream Provider Execution (with Retry & Fallback)     │
              │                                                         │
              ▼                                                         │
            [7] Budget Settlement & Refund                              │
              │                                                         │
              ▼                                                         │
            [8] Cache Write (Dual tier)                                 │
              ├── Exact Cache Store (Redis with TTL)                    │
              └── Semantic Cache Indexing (PostgreSQL + pgvector)       │
              │                                                         │
              ▼                                                         │
            [9] Async Usage Event (Published to Redis Stream)           │
              │                                                         │
              ▼                                                         │
            Return Provider Response (X-Tollgate-Cache: MISS) ◄─────────┘
```

### Why Exact Cache Precedes Semantic Cache
1. **Latency Efficiency:** Redis exact-match lookup completes in **~0.05 ms**, whereas embedding generation alone requires **~30 ms**. Checking exact match first eliminates 100% of embedding computation on exact cache hits.
2. **Economic Savings:** External embedding API calls consume network bandwidth, token quotas, and financial budget. Filtering out exact hits preserves embedding capacity.
3. **Deterministic Precedence:** Exact equality is the strongest possible guarantee of equivalence. Evaluating it first guarantees that identical requests never suffer vector approximation artifacts.

---

## 2. Storage Architecture: Decoupled PostgreSQL + Redis

The semantic cache uses a decoupled storage model to prevent database bloat and ensure zero response body duplication:

```text
PostgreSQL + pgvector (semantic_cache_entries)
 ├── id: UUID (Primary Key)
 ├── tenant_id: UUID (Indexed)
 ├── project_id: UUID (Indexed)
 ├── provider: str (e.g. "openai")
 ├── model: str (e.g. "gpt-4o")
 ├── cache_namespace: str
 ├── request_fingerprint: str (SHA-256 of generation parameters)
 ├── embedding: Vector(1536) (pgvector HNSW index)
 ├── embedding_model: str
 ├── embedding_version: str
 ├── response_cache_key: str (Reference to Redis response key)
 ├── created_at, expires_at, last_hit_at: Timestamp
 ├── hit_count: int
 └── metadata: JSONB (prompt length, model details)

Redis (Exact Cache Response Store)
 └── Key: tg:cache:res:{tenant}:{project}:{gen_ver}:{hash}
      └── Value: Full serialized ChatCompletionResponse JSON
```

### Response Dereference & Integrity Validation
When PostgreSQL returns a semantic match candidate:
1. The gateway extracts `response_cache_key`.
2. It fetches the raw payload from Redis.
3. It validates that the cached response belongs to the same `tenant_id` and `project_id`.
4. If Redis has expired or evicted the response, or if the payload is malformed, the gateway logs a warning, treats the candidate as a **cache miss**, and continues to the provider without raising an error.

---

## 3. Semantic Representation & Canonicalization

Raw JSON request bodies must never be embedded directly. Non-prompt formatting differences (field ordering, null values) would distort vector distance.

### Deterministic Message Sequence
Tollgate extracts all messages into a deterministic, versioned representation:

```text
role=system
content=You are a helpful database administrator.

role=user
content=How do I optimize a PostgreSQL query?
```

- Message order is strictly preserved.
- Message boundaries are explicitly delimited (`role=...\ncontent=...`).
- Content whitespace is trimmed but internal tokens are preserved.
- Semantics versioning is enforced via `SEMANTIC_REPRESENTATION_VERSION = "v1"`.

### Generation Fingerprinting
Non-semantic generation controls must match for a response to be safely reused. The `SemanticRepresentation.compute_generation_fingerprint` generates a SHA-256 hash across:
- `temperature`, `top_p`
- `max_tokens`
- `stop` sequences
- `seed`
- `presence_penalty`, `frequency_penalty`
- `response_format` (e.g., JSON schema)

---

## 4. Embedding Provider Abstraction

The semantic cache interacts with embedding models through an abstract interface:

```python
class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    async def embed(self, text: str) -> List[float]: ...
```

### Implementations
1. **MockEmbeddingProvider (Deterministic Local/Test Adapter):**
   - Generates deterministic 1536-dimensional unit-normalized float vectors.
   - Computes weighted semantic stem frequencies combined with MD5 token hashing.
   - Distinct actions (e.g., `"delete"` vs `"create"`) yield low similarity (< 0.70), enabling rigorous testing of false-hit boundaries without network dependencies.
2. **OpenAIEmbeddingProvider (Production Adapter):**
   - Connects asynchronously via `httpx.AsyncClient` to OpenAI-compatible endpoints (`/v1/embeddings`).
   - Supports configurable API keys, base URLs, timeouts, and models (`text-embedding-3-small`, `text-embedding-ada-002`).

---

## 5. PostgreSQL Schema & pgvector Indexing

### Alembic Migration: `0005_phase8_semantic_cache.py`
The migration applies the following operations:
1. Enables the vector extension: `CREATE EXTENSION IF NOT EXISTS vector`.
2. Creates table `semantic_cache_entries` with foreign keys to `tenants` and `projects`.
3. Creates composite B-tree index on `(tenant_id, project_id, provider, model, expires_at)`.
4. Creates an HNSW vector index:
   ```sql
   CREATE INDEX ix_semantic_cache_embedding ON semantic_cache_entries
   USING hnsw (embedding vector_cosine_ops)
   WITH (m = 16, ef_construction = 64);
   ```

### Distance Metric
The database uses cosine distance (`vector_cosine_ops`, operator `<=>`).
Similarity is computed as:
$$\text{similarity} = 1.0 - \text{cosine\_distance}$$

---

## 6. Conservative Safety Rules & Bypass Policy

Semantic caching is automatically bypassed when any of the following conditions are met:

| Condition | Action | Rationale |
| :--- | :--- | :--- |
| `stream=true` | **Bypass** | Streaming responses have distinct delivery semantics; semantic streaming replay is deferred to future phases. |
| `tools` defined | **Bypass** | Tool-augmented prompts may perform external side effects (database writes, emails, financial transactions). Replaying cached tool invocations risks side-effect corruption. |
| `tool_choice` != `"none"` | **Bypass** | Enforces tool safety invariants. |
| `n > 1` | **Bypass** | Multiple sample generation requires probabilistic variation from the upstream model. |
| Non-cacheable headers | **Bypass** | Honors explicit client no-cache directives. |

---

## 7. Similarity Threshold & Top-K Retrieval

- **Default Threshold:** `0.85` (configured via `TOLLGATE_SEMANTIC_CACHE_THRESHOLD`).
  > *Note: The default threshold is an initial safety-oriented configuration, not a scientifically validated universal constant. Workloads should tune this threshold using the offline evaluation harness.*
- **Top-K Limit:** `TOLLGATE_SEMANTIC_CACHE_TOP_K=5` (bounded internally to `max_candidates=20`).

---

## 8. Cache Invalidation & TTL

1. **TTL Expiration:** Entries include an `expires_at` timestamp based on `TOLLGATE_SEMANTIC_CACHE_TTL_SECONDS` (default: 86,400s / 24h). Expired entries are filtered out in SQL query predicates (`expires_at > NOW()`).
2. **Project Invalidation:**
   `DELETE /api/v1/projects/{project_id}/cache`
   - Atomically increments exact cache generation version in Redis.
   - Deletes all semantic cache entries for the project in PostgreSQL.
3. **Tenant Invalidation:**
   - Supported at service layer (`invalidate_tenant`) for multi-project tenant purges.

---

## 9. Budget & Usage Pipeline Integration

1. **Zero Provider Budget Consumed on Semantic Hits:**
   - Provider budget is **not reserved** and **not settled**.
   - Clients with exhausted spending budgets can still retrieve valid cached responses.
2. **Zero Fabricated Provider Usage Events:**
   - Semantic cache hits do not emit false token consumption events to the Redis stream.
   - Provider cost and provider tokens remain strictly $0.00 and 0.
3. **Rate Limiting Applies:**
   - Gateway token bucket rate limits are decremented on all requests, including semantic hits.

---

## 10. Fail-Open Architecture

The semantic cache is strictly fail-open:
- If embedding generation times out or fails $\rightarrow$ Bypass to upstream provider.
- If PostgreSQL connection fails $\rightarrow$ Bypass to upstream provider.
- If Redis response dereference fails $\rightarrow$ Bypass to upstream provider.
- If response integrity fails $\rightarrow$ Bypass to upstream provider.

A semantic cache failure **never** results in a user-visible 500 error.

---

## 11. Security & Multi-Tenant Isolation

1. **Tenant Isolation:** All PostgreSQL queries filter by `tenant_id = :tenant_id`. Cross-tenant retrieval is architecturally impossible.
2. **Project Isolation:** Queries filter by `project_id = :project_id`.
3. **Intra-Project Key Sharing:** Multiple API keys within the same project share semantic cache entries safely.
4. **Prompt & Response Privacy:** Raw prompt text is not indexed in PostgreSQL. Embeddings are stored without secret keys or authorization headers.
5. **Dereference Poisoning Defense:** Redis cached responses store ownership metadata; mismatched ownership triggers immediate eviction and bypass.

---

## 12. Observability & Metrics

Prometheus-compatible counters and histograms track semantic cache performance:

| Metric | Type | Description |
| :--- | :--- | :--- |
| `semantic_cache_requests_total` | Counter | Total requests evaluated for semantic caching. |
| `semantic_cache_hits_total` | Counter | Total accepted semantic cache hits. |
| `semantic_cache_misses_total` | Counter | Total semantic misses below threshold or no match. |
| `semantic_cache_bypasses_total` | Counter | Total requests bypassed due to safety rules. |
| `semantic_cache_errors_total` | Counter | Total fail-open errors encountered. |
| `semantic_cache_embedding_requests_total` | Counter | Total embedding generations requested. |
| `semantic_cache_embedding_errors_total` | Counter | Total embedding provider failures. |
| `semantic_cache_lookup_latency_seconds` | Histogram | Latency distribution of vector similarity queries. |
| `semantic_cache_embedding_latency_seconds` | Histogram | Latency distribution of embedding generation. |
| `semantic_cache_write_latency_seconds` | Histogram | Latency distribution of semantic indexing writes. |
| `semantic_cache_similarity_score` | Histogram | Distribution of candidate similarity scores. |

### Response Headers
- `X-Tollgate-Cache: HIT` — Exact cache match (L1)
- `X-Tollgate-Cache: SEMANTIC_HIT` — Semantic cache match (L2)
- `X-Tollgate-Cache: MISS` — Upstream provider execution (L3)

---

## 13. Offline Evaluation & Threshold Tuning

An evaluation harness in `evaluation/semantic_cache/` enables empirical measurement of precision, recall, false positive rate (FPR), and false negative rate (FNR) on synthetic and domain datasets.

### Measured Results on Benchmark Dataset:
```text
Threshold: 0.80 | Precision: 0.8333 | Recall: 1.0000 | FPR: 0.1667 | FNR: 0.0000
Threshold: 0.85 | Precision: 0.8333 | Recall: 1.0000 | FPR: 0.1667 | FNR: 0.0000
Threshold: 0.90 | Precision: 1.0000 | Recall: 1.0000 | FPR: 0.0000 | FNR: 0.0000
Threshold: 0.92 | Precision: 1.0000 | Recall: 1.0000 | FPR: 0.0000 | FNR: 0.0000
Threshold: 0.95 | Precision: 1.0000 | Recall: 0.8000 | FPR: 0.0000 | FNR: 0.2000
```
- At threshold **0.90**, the system achieves **100% precision with 0% false positives**, correctly rejecting dangerous near-matches (`"create database"` vs `"delete database"`).

---

## 14. Configuration Reference

```env
# Enable/Disable semantic cache (default: false)
TOLLGATE_SEMANTIC_CACHE_ENABLED=false

# Shadow mode: evaluate embeddings & candidates without returning cached responses
TOLLGATE_SEMANTIC_CACHE_SHADOW_MODE=false

# Embedding provider: "mock" (default) or "openai"
TOLLGATE_EMBEDDING_PROVIDER=mock
TOLLGATE_EMBEDDING_MODEL=text-embedding-3-small
TOLLGATE_EMBEDDING_DIMENSION=1536
TOLLGATE_EMBEDDING_TIMEOUT_SECONDS=2.0
TOLLGATE_EMBEDDING_API_KEY=
TOLLGATE_EMBEDDING_API_BASE=https://api.openai.com/v1

# Semantic similarity threshold (0.0 - 1.0)
TOLLGATE_SEMANTIC_CACHE_THRESHOLD=0.85

# Candidate search boundaries
TOLLGATE_SEMANTIC_CACHE_TOP_K=5
TOLLGATE_SEMANTIC_CACHE_MAX_CANDIDATES=20

# Cache entry TTL in seconds (default: 24 hours)
TOLLGATE_SEMANTIC_CACHE_TTL_SECONDS=86400

# Vector search query timeout in seconds
TOLLGATE_SEMANTIC_CACHE_LOOKUP_TIMEOUT_SECONDS=1.0
```

---

## 15. Rollout Strategy

1. **Phase 1 — Disabled Baseline:** Gateway runs with `TOLLGATE_SEMANTIC_CACHE_ENABLED=false`. All operations follow Phase 7 exact caching.
2. **Phase 2 — Shadow Evaluation:** Set `TOLLGATE_SEMANTIC_CACHE_SHADOW_MODE=true` on staging/canary. Embeddings and similarity scores are logged without returning cached responses to users.
3. **Phase 3 — Controlled Rollout:** Enable semantic cache with conservative threshold `0.90` on read-heavy, low-risk internal projects.
4. **Phase 4 — Domain Tuning:** Monitor `semantic_cache_similarity_score` distribution and tune threshold per domain.

---

## 16. Known Limitations & Deferred Features

- **No Cross-Model Semantic Reuse:** Responses are strictly bound to identical model identifiers.
- **No Streaming Replay:** `stream=true` bypasses semantic caching.
- **No Tool Caching:** Requests specifying `tools` bypass semantic caching.
- **No Learned Routing / Dynamic Thresholds:** Thresholds are static configuration values.
