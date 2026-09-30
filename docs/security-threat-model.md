# Tollgate Security Threat Model

## 1. System Overview & Architecture Boundary

Tollgate is a high-performance, multi-tenant LLM gateway providing:
- Unified OpenAI-compatible chat completion proxying
- Tenant and project identity isolation
- Cryptographic API-key lifecycle management and role-based access control (RBAC)
- Token-bucket distributed rate limiting
- Real-time pre-allocation budget enforcement and settlement
- Exact and semantic response caching
- Learned quality/cost-aware model routing
- Resilience (exponential backoff retries, timeouts, fallback, and circuit breakers)
- Streaming SSE proxying
- Asynchronous usage telemetry and cost accounting pipeline
- Tenant dashboard and operational metrics (OpenTelemetry and Prometheus)

---

## 2. Identified Assets

1. **API Keys**: Secret credentials (`tg_live_...`) authorizing gateway requests and management actions.
2. **Tenant Identity**: Organizational boundaries (`tenant_id`), isolation domains, and tenant configurations.
3. **Project Identity**: Workspace sub-domains (`project_id`), project-scoped budgets, caches, and API keys.
4. **User Identity**: User accounts, emails, password hashes, and assigned tenant roles (`owner`, `admin`, `viewer`).
5. **Provider Credentials**: Upstream API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) configured in Tollgate.
6. **Database Credentials**: PostgreSQL connection strings and operational database state.
7. **Redis Credentials**: Redis connection strings, cache keys, token bucket keys, and stream buffers.
8. **Prompts**: Customer text prompts, system messages, conversation history, and user intent.
9. **Responses**: Upstream LLM completions, generated output text, and streaming SSE tokens.
10. **Tool-Call Data**: Function definitions, names, arguments, and returned tool results.
11. **Embeddings**: Vector representations generated for semantic similarity matching.
12. **Usage Data**: Usage events, token counts, request identifiers, timestamps, and rollup records.
13. **Cost & Budget Information**: Balance tracking, microdollar limits, spend reservations, and pricing models.
14. **Routing Information**: Classifier confidence scores, routing features, route choices (`cheap` vs `strong`), and fallback states.
15. **Telemetry**: Distributed traces (OTel spans), Prometheus metrics, audit logs, and request correlation IDs.

---

## 3. Threat Actors

- **Unauthenticated Attacker**: External actor without valid credentials seeking unauthorized access, credential brute-forcing, denial of service, or endpoint enumeration.
- **Authenticated Tenant**: Legitimate customer seeking to access other tenants' data (cross-tenant BOLA/IDOR), bypass rate limits, or poison shared resources.
- **Malicious Tenant User**: Authenticated user within a tenant attempting privilege escalation (e.g. `viewer` attempting `owner` administrative operations).
- **Compromised API Key**: Key leaked in customer code or git repositories used by an unauthorized party.
- **Malicious Client**: Authorized caller attempting resource exhaustion via oversized payloads, huge token counts, or connection floods.
- **Malicious Prompt**: Prompt injection, adversarial input designed to poison the semantic cache, or cause model confusion.
- **Malicious Provider Response**: Broken, corrupted, or crafted response from an upstream provider or mock endpoint.
- **Compromised Provider**: Upstream provider returning errors, high latencies, or malicious payloads.
- **Malicious Dashboard User**: User attempting SQL injection, XSS via response rendering, or unauthorized analytics exfiltration.

---

## 4. Threat Matrix

### Threat 1: API Key Extraction & Enumeration
- **Asset**: API Keys, Tenant Identity
- **Attacker**: Unauthenticated Attacker
- **Attack Surface**: `POST /v1/chat/completions`, `GET /api/v1/dashboard/*`, `Authorization: Bearer <key>`
- **Attack**: Attacker attempts to brute-force API keys or probe error messages to distinguish between valid, revoked, and nonexistent keys.
- **Impact**: Unauthorized gateway access, stolen spend budgets, data leakage.
- **Existing Mitigation**: Cryptographically secure 256-bit random key generation (`secrets.token_urlsafe(32)`), non-secret prefix indexing (`tg_live_...`), SHA-256 key hashing (`APIKey.key_hash`), raw key never persisted.
- **New Mitigation**: Constant-time hash verification (`hmac.compare_digest`), normalized generic 401 error response (`"Invalid or expired API key"`) regardless of failure reason, zero existence distinction.
- **Test**: `tests/security/test_auth_security.py::test_auth_enumeration_prevention`, `test_auth_invalid_and_revoked_keys`
- **Residual Risk**: Low. 256 bits of entropy prevents online brute force.

---

### Threat 2: Cross-Tenant Data Access (BOLA / IDOR)
- **Asset**: Projects, API Keys, Usage Data, Budgets, Analytics
- **Attacker**: Authenticated Tenant A
- **Attack Surface**: `GET /api/v1/dashboard/*`, `GET /api/v1/usage`, `DELETE /api/v1/projects/{id}/cache`, `PUT /api/v1/projects/{id}/budget`
- **Attack**: Tenant A supplies Tenant B's UUID in the path or query parameter of an authenticated request.
- **Impact**: Leakage of competitors' usage events, spend, model choices, or unauthorized budget modification.
- **Existing Mitigation**: Queries filter on `ctx.tenant_id`.
- **New Mitigation**: Strict server-derived tenant enforcement. Cross-tenant IDs return normalized HTTP 404 (or 403) without leaking existence. `get_effective_budget_limits` enforces `Project.tenant_id == tenant_id`.
- **Test**: `tests/security/test_tenant_isolation_security.py`, `tests/security/test_idor_security.py`
- **Residual Risk**: Minimal. Server-derived identity is authoritative across all DB statements.

---

### Threat 3: RBAC Privilege Escalation
- **Asset**: API Keys, Budgets, Cache Purge, Tenant Users
- **Attacker**: Malicious Tenant User (`viewer`)
- **Attack Surface**: `POST /api/v1/projects/{id}/api-keys`, `DELETE /api/v1/api-keys/{id}`, `PUT /api/v1/projects/{id}/budget`, `DELETE /api/v1/projects/{id}/cache`
- **Attack**: A read-only viewer issues administrative write or delete requests directly against the REST API.
- **Impact**: Unauthorized API key creation, budget modification, or denial-of-service via cache invalidation.
- **Existing Mitigation**: `verify_role_permissions` checks `["owner", "admin"]`.
- **New Mitigation**: Explicit server-side role enforcement on every mutation endpoint; dashboard endpoints verify permissions before executing DB statements.
- **Test**: `tests/security/test_rbac_security.py`
- **Residual Risk**: Negligible. Roles are resolved from database-backed keys and verified server-side.

---

### Threat 4: Cache Poisoning & Cross-Tenant Cache Leakage (Exact Cache)
- **Asset**: Prompts, Responses, Tenant Isolation
- **Attacker**: Authenticated Tenant A
- **Attack Surface**: `POST /v1/chat/completions` (Exact Cache)
- **Attack**: Tenant A sends identical prompt as Tenant B hoping to receive Tenant B's cached response, or populate Tenant B's cache entry.
- **Impact**: Prompt and response leakage across tenant boundaries.
- **Existing Mitigation**: Exact cache key includes tenant UUID and project UUID in key prefix.
- **New Mitigation**: `Canonicalizer.compute_hash` embeds `tenant_id` and `project_id` inside the canonical SHA-256 payload and key namespace (`tg:cache:res:<tenant_id>:<project_id>:...`). Streaming and tool requests bypass cache. Failed provider responses are never written to cache.
- **Test**: `tests/security/test_cache_security.py::test_exact_cache_tenant_isolation`
- **Residual Risk**: Negligible. Complete cryptographic and namespace partitioning.

---

### Threat 5: Semantic Cache Poisoning & Persona Collisions
- **Asset**: System Prompts, Medical/Financial/Confidential LLM Responses
- **Attacker**: Malicious Tenant Client / Adversarial Prompt
- **Attack Surface**: `POST /v1/chat/completions` (Semantic Cache)
- **Attack**: Attacker sends a prompt that is semantically similar in user text to an existing entry, but has different system instructions (e.g., jailbreak persona) or belongs to another tenant.
- **Impact**: Bypassing guardrails, persona hijacking, or cross-tenant cache retrieval.
- **Existing Mitigation**: Vector queries filter on `tenant_id` and `project_id`.
- **New Mitigation**: Semantic fingerprint (`compute_fingerprint`) incorporates a cryptographic hash of all system messages (`system_hash`), sampling parameters, model, and tenant/project IDs. Differing system instructions yield completely different fingerprints, preventing candidate retrieval.
- **Test**: `tests/security/test_cache_security.py::test_semantic_cache_system_instruction_isolation`
- **Residual Risk**: Low. Bound by vector similarity threshold (0.85) and strict fingerprint equality.

---

### Threat 6: Resource Exhaustion & Denial of Service (DoS)
- **Asset**: Gateway Availability, Redis Memory, PostgreSQL Connections
- **Attacker**: Malicious Client / Unauthenticated Attacker
- **Attack Surface**: `POST /v1/chat/completions`
- **Attack**: Attacker submits huge JSON payloads (gigabytes), 100,000 messages, extreme `max_tokens` (999,999,999), or thousands of tool schemas.
- **Impact**: Memory exhaustion, thread blocking, database or provider credit exhaustion.
- **Existing Mitigation**: Distributed token-bucket rate limiting (Phase 4).
- **New Mitigation**: Pydantic schema validation enforcement:
  - Max messages: 1,000
  - Max prompt total characters: 2,000,000
  - Max message characters: 500,000
  - Max tokens limit: 128,000
  - Max tool definitions: 64 (function name <= 64 chars, description <= 1024 chars)
  - Max `n`: 10
  - Model name: <= 256 chars
- **Test**: `tests/security/test_request_validation_security.py`
- **Residual Risk**: Low. Network-level DDoS is handled at reverse proxy/infrastructure layer.

---

### Threat 7: Budget Tampering & Double-Spending
- **Asset**: Cost / Budget Information, Provider Balance
- **Attacker**: Malicious Authenticated Tenant
- **Attack Surface**: `POST /v1/chat/completions`, `PUT /api/v1/tenants/{id}/budget`
- **Attack**: Concurrent requests racing against budget balance, negative budget limits, or client forging cost headers.
- **Impact**: Unbounded financial loss, negative account balances, database corruption.
- **Existing Mitigation**: Redis Lua scripts for atomic pre-allocation and reservation (`BUDGET_RESERVE_LUA`, `BUDGET_SETTLE_LUA`).
- **New Mitigation**:
  - Costs are calculated server-side exclusively by `PricingService` from verified token counts; client cost headers are ignored.
  - Budget updates validate `ge=0` and `le=1_000_000_000_000_000`.
  - Settlements are strictly idempotent and reject replayed or cross-tenant reservations.
- **Test**: `tests/security/test_budget_security.py`
- **Residual Risk**: Negligible. Atomic Redis transactions prevent race conditions.

---

### Threat 8: Telemetry Leakage (OTel Spans & Prometheus Metrics)
- **Asset**: Prompts, Responses, API Keys, Provider Secrets
- **Attacker**: Observability Consumer / Metrics Scraper
- **Attack Surface**: `/metrics`, OTLP Trace Exporter, Application Logs
- **Attack**: LLM prompts, completions, customer PII, or raw API keys appear in Prometheus labels or OpenTelemetry spans.
- **Impact**: Sensitive enterprise data exfiltrated to log aggregation systems or metrics dashboards.
- **Existing Mitigation**: `safe_set_attribute` filters sensitive keys and regex patterns.
- **New Mitigation**:
  - `metrics.py` enforces bounded cardinality; high-cardinality values (`tenant_id`, `request_id`, `prompt`, `key_id`) are forbidden as Prometheus labels.
  - OTel spans strictly drop prompt and completion bodies.
  - Bearer headers and API key hashes are redacted.
- **Test**: `tests/security/test_error_and_telemetry_leakage.py`
- **Residual Risk**: Low. Comprehensive sanitization in middleware and trace instrumentation.

---

### Threat 9: SQL Injection in Dashboard Analytics
- **Asset**: Database Credentials, Usage Data, Relational Store
- **Attacker**: Malicious Dashboard User
- **Attack Surface**: `GET /api/v1/dashboard/requests`, `sort_by`, `search`, `model`, `provider`
- **Attack**: Injecting SQL syntax (`' OR 1=1 --`, `UNION SELECT`) via filter parameters.
- **Impact**: Arbitrary database readout, authentication bypass.
- **Existing Mitigation**: SQLAlchemy ORM queries.
- **New Mitigation**: Fully parameterized SQLAlchemy expressions; explicit column whitelist mapping for dynamic sorting (`sortable_columns`); strict boolean evaluation of sort directions; ilike parameterization for search strings.
- **Test**: `tests/security/test_sql_injection_security.py`
- **Residual Risk**: Negligible. Zero string-concatenated SQL queries in codebase.

---

### Threat 10: Stack Trace & Error Detail Leakage
- **Asset**: Internal Architecture, File Paths, Database Dialects
- **Attacker**: Unauthenticated / Authenticated Attacker
- **Attack Surface**: Any endpoint triggering an unhandled 500 error
- **Attack**: Triggering unexpected database disconnections or invalid formats to inspect exception tracebacks.
- **Impact**: Information disclosure assisting vulnerability reconnaissance.
- **Existing Mitigation**: Custom validation handlers for 400, 429, 402.
- **New Mitigation**: Global unhandled `Exception` handler intercepting all uncaught errors, logging tracebacks securely internally with `request_id`, and returning standardized OpenAI-compatible error payloads (`{"error": {"message": "An internal server error occurred.", "type": "internal_server_error"}}`).
- **Test**: `tests/security/test_error_and_telemetry_leakage.py::test_unhandled_exception_sanitization`
- **Residual Risk**: Negligible. Safe standardized envelopes for all status codes.
