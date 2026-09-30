# Production Configuration & Hardening Guide (Phase 14)

## Overview

This document defines the configuration parameters, environment variables, network exposure policies, and database/cache hardening standards required to run Tollgate in production securely.

---

## 1. Setting Categorization Matrix

All settings are categorized into five operational tiers:
* **[REQUIRED]**: Must be explicitly set; deployment will fail or refuse to start safely without them.
* **[RECOMMENDED]**: Sensible defaults exist, but production tuning is strongly advised.
* **[DEVELOPMENT ONLY]**: Must NEVER be enabled in production environments.
* **[PRODUCTION ONLY]**: Pertains specifically to staging or production topologies (e.g., behind TLS reverse proxies).
* **[SECURITY SENSITIVE]**: Holds credentials, secrets, or keys. Must be stored in a secrets manager or encrypted environment store.

| Environment Variable | Category | Default | Description |
| :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | [REQUIRED] | `development` | Deployment environment: `production`, `staging`, or `development`. |
| `DATABASE_URL` | [REQUIRED] [SECURITY SENSITIVE] | None | PostgreSQL async connection string with least-privilege credentials. |
| `POSTGRES_PASSWORD` | [REQUIRED] [SECURITY SENSITIVE] | None | Secret password for PostgreSQL application role. |
| `REDIS_URL` | [REQUIRED] [SECURITY SENSITIVE] | `redis://redis:6379/0` | Authenticated Redis connection URL (`redis://:password@host:port/0`). |
| `SECRET_KEY` | [REQUIRED] [SECURITY SENSITIVE] | None | Cryptographic secret for signing session/JWT authentication tokens. |
| `METRICS_TOKEN` | [REQUIRED] [SECURITY SENSITIVE] | None | Bearer token required to access the Prometheus `/metrics` endpoint. |
| `OPENAI_API_KEY` | [SECURITY SENSITIVE] | None | Upstream provider API credential for OpenAI model endpoints. |
| `ANTHROPIC_API_KEY` | [SECURITY SENSITIVE] | None | Upstream provider API credential for Anthropic model endpoints. |
| `TOLLGATE_CORS_ALLOWED_ORIGINS` | [RECOMMENDED] | `["*"]` (dev only) | Explicit list of trusted origins (e.g., `["https://app.tollgate.ai"]`). |
| `TOLLGATE_DOCS_ENABLED` | [PRODUCTION ONLY] | `true` | Set to `false` in production to disable OpenAPI `/docs` and `/redoc`. |
| `TOLLGATE_ENABLE_HSTS` | [PRODUCTION ONLY] | `false` | Set to `true` when deployed behind HTTPS to emit `Strict-Transport-Security`. |
| `TOLLGATE_TRUSTED_PROXIES` | [PRODUCTION ONLY] | `["127.0.0.1", "::1"]` | Allowed upstream reverse proxy IPs for parsing `X-Forwarded-For`. |
| `TOLLGATE_RATE_LIMIT_ENABLED` | [RECOMMENDED] | `true` | Enables distributed token-bucket rate limiting in Redis. |
| `TOLLGATE_CIRCUIT_BREAKER_ENABLED`| [RECOMMENDED] | `true` | Enables adaptive provider health tracking and failover protection. |
| `TOLLGATE_OTEL_ENABLED` | [RECOMMENDED] | `false` | Enables OpenTelemetry distributed tracing export. |
| `TOLLGATE_OTEL_ENDPOINT` | [RECOMMENDED] | `http://localhost:4318` | OTLP HTTP/gRPC exporter endpoint. |
| `RELOAD` (uvicorn) | [DEVELOPMENT ONLY] | `false` in prod | Live code reloading. Strictly disabled in production. |

---

## 2. Secure Defaults vs. Development Overrides

| Setting | Development Default | Production Default | Rationale |
| :--- | :--- | :--- | :--- |
| **CORS Origins** | Wildcard `*` without credentials | Explicit origins with credentials | Protects against cross-origin credential extraction and CSRF. |
| **Interactive Docs** | Enabled (`/docs`, `/redoc`) | Disabled or restricted | Prevents external reconnaissance of internal schema structures. |
| **Uvicorn Reload** | Enabled (`reload=True`) | Disabled (`reload=False`) | Avoids unexpected worker restarts and dev-server file-watcher vulnerabilities. |
| **Database Binding** | `127.0.0.1:5432` | Internal Docker / VPC network only | Prevents public internet access to database engines. |
| **Redis Binding** | `127.0.0.1:6379` | Internal Docker / VPC network only | Prevents unauthenticated/authenticated exposure to public networks. |
| **HSTS** | Disabled (plain HTTP testing) | Enabled (`max-age=31536000`) | Forces modern browsers to use TLS connections. |

---

## 3. Redis Security & Hardening Standards

1. **Authentication (`requirepass`)**:
   - Redis must be configured with a high-entropy passphrase via `requirepass <strong-password>`.
   - The Tollgate application must supply this password in `REDIS_URL`.
2. **Network Isolation**:
   - In `docker-compose.yml`, Redis is bound strictly to `127.0.0.1` and isolated on `tollgate-backend`.
   - External clients cannot connect to Redis directly.
3. **Memory Limits & Eviction Policy**:
   - Set `maxmemory 2gb` (or tailored to workload).
   - Set `maxmemory-policy volatile-lru` or `allkeys-lru` so ephemeral cache items expire safely without exhausting host memory.
4. **Dangerous Commands Disabled**:
   - In `redis.conf`, rename or disable dangerous administrative commands:
     ```text
     rename-command FLUSHALL ""
     rename-command FLUSHDB ""
     rename-command CONFIG ""
     rename-command KEYS ""
     ```
5. **Key Namespace Separation**:
   - Rate limiting: `tg:ratelimit:*`
   - Exact cache: `tg:cache:*`
   - Semantic cache: `tg:semcache:*`
   - Circuit breaker: `tg:cb:*`
   - Usage streams: `tg:usage:*`

---

## 4. PostgreSQL Security & Least Privilege

1. **Role Separation**:
   - Tollgate must never connect to PostgreSQL using the `postgres` superuser.
   - A dedicated application role `tollgate_app` must be created with `CONNECT`, `SELECT`, `INSERT`, `UPDATE`, and `DELETE` on tables in the schema, but NO superuser or cluster administration rights.
2. **Connection Pools & Limits**:
   - AsyncPG pool size must be bounded (`max_size=20`) to prevent database connection exhaustion.
3. **Network Isolation**:
   - PostgreSQL port `5432` is bound to `127.0.0.1` in development and isolated within the Docker private network `tollgate-backend`.

---

## 5. Reverse Proxy & Forwarded Header Trust

When Tollgate runs behind NGINX, Cloudflare, Traefik, or AWS ALB:
* **Anti-Spoofing Architecture**:
  - The application uses `resolve_client_ip()` from `tollgate_core.security`.
  - Untrusted clients sending spoofed `X-Forwarded-For` headers are ignored. Only trusted proxies configured in `TOLLGATE_TRUSTED_PROXIES` are permitted to forward upstream client IPs.
* **TLS Termination**:
  - Reverse proxies must terminate TLS and forward `X-Forwarded-Proto: https`.
  - The gateway inspects `X-Forwarded-Proto` and injects `Strict-Transport-Security: max-age=31536000; includeSubDomains`.

---

## 6. Server-Side Request Forgery (SSRF) Audit

* **Surface Analysis**:
  - Tollgate does NOT accept client-controlled outbound URLs.
  - Model requests are dispatched exclusively to verified upstream provider base URLs (e.g. `https://api.openai.com`, `https://api.anthropic.com`) configured in server-side configuration.
  - The client cannot supply arbitrary endpoints, webhooks, or redirect targets.
* **Finding**:
  ```text
  SSRF attack surface not currently exposed.
  ```
