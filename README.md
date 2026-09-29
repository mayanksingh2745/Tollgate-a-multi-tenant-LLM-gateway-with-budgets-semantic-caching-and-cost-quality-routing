# Tollgate: Multi-Tenant LLM Gateway

[![CI Pipeline](https://github.com/mayanksingh2745/Tollgate-a-multi-tenant-LLM-gateway-with-budgets-semantic-caching-and-cost-quality-routing/actions/workflows/ci.yml/badge.svg)](https://github.com/mayanksingh2745/Tollgate-a-multi-tenant-LLM-gateway-with-budgets-semantic-caching-and-cost-quality-routing/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.2+-61DAFB.svg)](https://react.dev/)

Tollgate is an enterprise-grade multi-tenant LLM gateway designed to prevent runaway costs, enforce per-project monthly budgets, provide automatic provider failover, enable high-performance semantic caching, and maintain token accounting precision across streaming and concurrent workloads.

---

## Phase 1: Multi-Tenancy + API Key Authentication

Phase 1 establishes the core identity, project hierarchy, RBAC, and secure API key authentication engine.

### Core Domain Hierarchy

```
Tenant
 ├── Users (owner / admin / viewer)
 └── Projects
      └── API Keys (tg_live_...)
```

---

## API Reference (Phase 1 Endpoints)

### 1. Tenants

- `POST /api/v1/tenants` — Create a new tenant (`{"name": "...", "slug": "..."}`)
- `GET /api/v1/tenants/{tenant_id}` — Retrieve tenant details (Enforces Tenant Isolation)

### 2. Users

- `POST /api/v1/tenants/{tenant_id}/users` — Create user (`owner`, `admin`, or `viewer` with Argon2id password hashing)
- `GET /api/v1/tenants/{tenant_id}/users` — List users in tenant

### 3. Projects

- `POST /api/v1/tenants/{tenant_id}/projects` — Create project under tenant
- `GET /api/v1/tenants/{tenant_id}/projects` — List projects in tenant
- `GET /api/v1/tenants/{tenant_id}/projects/{project_id}` — Retrieve project details

### 4. API Keys

- `POST /api/v1/projects/{project_id}/api-keys` — Generate new API key (Returns raw key `tg_live_...` **ONLY ONCE**)
- `GET /api/v1/projects/{project_id}/api-keys` — List API key metadata (Excludes raw secrets)
- `DELETE /api/v1/api-keys/{api_key_id}` — Revoke an API key
- `POST /api/v1/api-keys/{api_key_id}/rotate` — Rotate API key (Revokes old key, generates new active key)

---

## Quick Start (Docker Compose)

Launch the complete stack (FastAPI + PostgreSQL + Redis + Worker + React Dashboard) with a single command:

```bash
docker compose up --build
```

---

## Authentication Flow & Security Guarantees

1. **Header**: `Authorization: Bearer tg_live_xxxxxxxx...`
2. **Prefix Lookup**: Looks up candidate records via indexed prefix (`key_prefix = tg_live_a8f3d91c`).
3. **Constant-Time Verification**: Compares raw key hash against stored SHA-256 hash using `hmac.compare_digest`.
4. **Tenant Isolation**: Guarantees API keys belonging to Tenant A can NEVER access or mutate Tenant B resources.

See [`docs/authentication.md`](docs/authentication.md) for full architectural specifications.

---

## Local Development & Testing

```bash
# Run test suite
pytest
```
