# Tollgate Role-Based Access Control (RBAC) Matrix

## 1. Overview & Role Hierarchy

Tollgate implements server-side Role-Based Access Control enforced at the API route boundary via FastAPI dependencies and the `verify_role_permissions` engine.

The system defines three core tenant roles in a strict hierarchy:

```text
       ┌───────────┐
       │   Owner   │  Full tenant ownership, budget administration, key creation/revocation, member management
       └─────┬─────┘
             │ (inherits)
             ▼
       ┌───────────┐
       │   Admin   │  Project management, API key management, cache invalidation, analytics read
       └─────┬─────┘
             │ (inherits)
             ▼
       ┌───────────┐
       │  Viewer   │  Read-only telemetry, usage inspection, dashboard analytics (project-scoped or tenant-scoped)
       └───────────┘
```

Role mapping:
- **`owner`**: Can perform all administrative and read operations within their tenant.
- **`admin`**: Can manage API keys, projects, view analytics, and invalidate caches. Cannot perform organizational owner-only destruction.
- **`viewer`**: Can query read-only analytics, inspect usage events and rollups, view request metadata, and read current profile. Cannot modify budgets, generate keys, or invalidate caches.
- **`unauthorized`**: Unauthenticated caller (no key or invalid key). Denied access to all protected resources (HTTP 401).

---

## 2. Server-Side Enforcement Mechanism

RBAC is enforced via:
- `gateway.src.auth.dependencies.get_current_api_key`: Resolves the caller's `AuthenticatedContext` (tenant_id, project_id, role, user_id, api_key_id).
- `gateway.src.auth.permissions.verify_role_permissions(ctx, allowed_roles)`: Evaluates the role against the allowed hierarchy. If the user's role does not satisfy the requirement, raises HTTP 403 Forbidden:
  ```json
  {
    "detail": "Insufficient permissions for this action."
  }
  ```
- **Tenant Scope Guard**: If a caller attempts to interact with an object or parameter outside their `ctx.tenant_id`, the system raises HTTP 404 Not Found (or 403) to prevent cross-tenant enumeration.
- **Project Scope Guard**: Viewers tied to a specific project (`ctx.project_id`) are prevented from viewing or querying other projects' telemetry.

---

## 3. Comprehensive RBAC Matrix

| Endpoint | Method | Operation Description | Minimum Role | Owner | Admin | Viewer | Unauthenticated |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Chat Completions** | | | | | | | |
| `/v1/chat/completions` | `POST` | Execute chat proxy request | Any active key |  Allowed |  Allowed |  Allowed | ❌ 401 |
| **Tenant Management** | | | | | | | |
| `/api/v1/tenants` | `POST` | Create Tenant (Bootstrap) | Bootstrap |  Allowed |  Allowed |  Allowed |  Allowed (Bootstrap) |
| `/api/v1/tenants/{id}` | `GET` | Get Tenant Details | Any active key in tenant |  Allowed |  Allowed |  Allowed | ❌ 401 |
| **User Management** | | | | | | | |
| `/api/v1/tenants/{id}/users` | `POST` | Create Tenant User | `owner`, `admin` |  Allowed |  Allowed | ❌ 403 | ❌ 401 |
| `/api/v1/tenants/{id}/users` | `GET` | List Tenant Users | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| **Project Management** | | | | | | | |
| `/api/v1/tenants/{id}/projects` | `POST` | Create Project | `owner`, `admin` |  Allowed |  Allowed | ❌ 403 | ❌ 401 |
| `/api/v1/tenants/{id}/projects` | `GET` | List Tenant Projects | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/tenants/{id}/projects/{pid}`| `GET` | Get Project Details | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| **API Key Management** | | | | | | | |
| `/api/v1/projects/{pid}/api-keys` | `POST` | Generate New API Key | `owner`, `admin` |  Allowed |  Allowed | ❌ 403 | ❌ 401 |
| `/api/v1/projects/{pid}/api-keys` | `GET` | List API Keys (Metadata) | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/api-keys/{id}` | `DELETE` | Revoke API Key | `owner`, `admin` |  Allowed |  Allowed | ❌ 403 | ❌ 401 |
| `/api/v1/api-keys/{id}/rotate` | `POST` | Rotate API Key | `owner`, `admin` |  Allowed |  Allowed | ❌ 403 | ❌ 401 |
| **Budget Management** | | | | | | | |
| `/api/v1/tenants/{id}/budget` | `GET` | Get Tenant Budget Limits | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/tenants/{id}/budget` | `PUT` | Update Tenant Budget | `owner`, `admin` |  Allowed |  Allowed | ❌ 403 | ❌ 401 |
| `/api/v1/projects/{id}/budget` | `GET` | Get Project Budget Limits | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/projects/{id}/budget` | `PUT` | Update Project Budget | `owner`, `admin` |  Allowed |  Allowed | ❌ 403 | ❌ 401 |
| **Cache Management** | | | | | | | |
| `/api/v1/projects/{pid}/cache` | `DELETE`| Invalidate Project Cache | `owner`, `admin` |  Allowed |  Allowed | ❌ 403 | ❌ 401 |
| `/api/v1/projects/{pid}/cache/semantic`| `GET`| Inspect Semantic Metadata | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| **Usage & Cost Accounting** | | | | | | | |
| `/api/v1/usage` | `GET` | Query Usage Events | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/usage/rollups/daily` | `GET` | Daily Rollup Aggregations | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/usage/rollups/monthly` | `GET` | Monthly Rollup Aggregations| `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| **Dashboard Analytics** | | | | | | | |
| `/api/v1/dashboard/me` | `GET` | Current Profile & Scopes | Any active key |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/overview` | `GET` | Executive KPI Overview | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/usage` | `GET` | Time-Series Usage Graph | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/costs` | `GET` | Spend Breakdown Analysis | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/budgets` | `GET` | Budget Utilization Status | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/models` | `GET` | Model Performance Breakdown| `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/providers` | `GET` | Provider Latency/Success | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/cache` | `GET` | Cache Hit Rate Analytics | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/router` | `GET` | Model Router Savings KPI | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/requests` | `GET` | Filtered Request Explorer | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/requests/{id}` | `GET` | Request Safe Detail | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/projects` | `GET` | Dashboard Projects Summary| `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| `/api/v1/dashboard/api-keys` | `GET` | Tenant API Key Metadata | `owner`, `admin`, `viewer` |  Allowed |  Allowed |  Allowed | ❌ 401 |
| **System Operations** | | | | | | | |
| `/metrics` | `GET` | Prometheus Metric Scrape | Bearer Token Auth |  Allowed (Token) |  Allowed (Token) |  Allowed (Token) | ❌ 401 |
| `/healthz`, `/livez`, `/readyz` | `GET` | Liveness/Readiness Probes | Public |  Allowed |  Allowed |  Allowed |  Allowed |

---

## 4. Security Invariants

1. **Frontend Non-Reliance**: Server-side endpoints strictly perform their own authorization checks. Frontend UI masking is solely for user experience and carries zero security trust.
2. **Project-Scoped Viewer Lockdown**: If an API key is restricted to `project_id = X`, attempts by that key to access dashboard analytics or usage for `project_id = Y` are denied (HTTP 403) or filtered exclusively to project X.
3. **No Key Exfiltration**: Viewers and Admins listing keys via `/api/v1/dashboard/api-keys` or `/api/v1/projects/{id}/api-keys` only receive the `key_prefix`, creation dates, and metadata. The raw secret key is cryptographically erased and unrecoverable from the database.
