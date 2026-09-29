# Tollgate: Multi-Tenant LLM Gateway

[![CI Pipeline](https://github.com/mayanksingh2745/Tollgate-a-multi-tenant-LLM-gateway-with-budgets-semantic-caching-and-cost-quality-routing/actions/workflows/ci.yml/badge.svg)](https://github.com/mayanksingh2745/Tollgate-a-multi-tenant-LLM-gateway-with-budgets-semantic-caching-and-cost-quality-routing/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.2+-61DAFB.svg)](https://react.dev/)

Tollgate is an enterprise-grade multi-tenant LLM gateway designed to prevent runaway costs, enforce per-project monthly budgets, provide automatic provider failover, enable high-performance semantic caching, and maintain token accounting precision across streaming and concurrent workloads.

---

## Implemented Phases

- **Phase 0 — Engineering Foundation**: FastAPI, AsyncPG, Redis, React Dashboard, Docker Compose, Alembic.
- **Phase 1 — Multi-Tenancy & API Key Authentication**: Tenant & Project hierarchy, RBAC (`owner`, `admin`, `viewer`), secure API key generation & constant-time hash verification.
- **Phase 2 — OpenAI-Compatible LLM Gateway**: `/v1/chat/completions` proxy supporting standard OpenAI client SDKs, non-streaming & SSE streaming, provider abstraction, request tracking, and timeouts.

---

## OpenAI-Compatible Gateway (`/v1/chat/completions`)

Tollgate acts as a drop-in replacement for any OpenAI-compatible API. Point your OpenAI SDK or HTTP client directly to Tollgate:

### Python Example (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    api_key="tg_live_your_tollgate_api_key_here",
    base_url="http://localhost:8000/v1"
)

# Non-streaming request
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Explain asynchronous programming in Python"}],
    stream=False
)
print(response.choices[0].message.content)

# Streaming request (SSE)
stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Count from 1 to 5"}],
    stream=True
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

See [`docs/gateway.md`](docs/gateway.md) for full endpoint specifications, streaming lifecycle, and timeout configurations.

---

## API Reference

### Gateway
- `POST /v1/chat/completions` — OpenAI-compatible chat completions (Non-streaming & SSE Streaming)

### Multi-Tenancy & Identity (Phase 1)
- `POST /api/v1/tenants` — Create tenant
- `GET /api/v1/tenants/{tenant_id}` — Get tenant details
- `POST /api/v1/tenants/{tenant_id}/users` — Create user (Argon2id password hashing)
- `GET /api/v1/tenants/{tenant_id}/users` — List users in tenant
- `POST /api/v1/tenants/{tenant_id}/projects` — Create project
- `GET /api/v1/tenants/{tenant_id}/projects` — List projects in tenant
- `POST /api/v1/projects/{project_id}/api-keys` — Generate API key (Raw secret returned **ONLY ONCE**)
- `GET /api/v1/projects/{project_id}/api-keys` — List API key metadata
- `DELETE /api/v1/api-keys/{api_key_id}` — Revoke API key
- `POST /api/v1/api-keys/{api_key_id}/rotate` — Rotate API key

---

## Quick Start (Docker Compose)

Launch the complete stack (FastAPI + PostgreSQL + Redis + Worker + React Dashboard) with a single command:

```bash
docker compose up --build
```

---

## Local Development & Testing

```bash
# Run complete test suite (unit + integration + OpenAI SDK compatibility)
pytest
```
