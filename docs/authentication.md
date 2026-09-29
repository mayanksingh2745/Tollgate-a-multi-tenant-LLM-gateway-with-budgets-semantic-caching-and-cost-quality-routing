# Tollgate Authentication & Multi-Tenancy Architecture

This document details the API key authentication, password hashing, RBAC model, and multi-tenant isolation guarantees implemented in Tollgate Phase 1.

---

## 1. Authentication Flow Diagram

```
                 +--------------------------------+
                 |       Client Application       |
                 +---------------+----------------+
                                 |
                     Authorization: Bearer <key>
                                 |
                                 v
                 +---------------+----------------+
                 |    API Key Prefix Lookup       |
                 |     (Key Prefix: tg_live_)     |
                 +---------------+----------------+
                                 |
                                 v
                 +---------------+----------------+
                 |   Constant-Time Hash Verify    |
                 |     (SHA-256 HMAC Compare)     |
                 +---------------+----------------+
                                 |
                                 v
                 +---------------+----------------+
                 | Status & Expiration Validation |
                 | (Check status & expires_at)    |
                 +---------------+----------------+
                                 |
                                 v
                 +---------------+----------------+
                 | Project & Tenant Context Bind  |
                 +---------------+----------------+
                                 |
                                 v
                 +---------------+----------------+
                 |      AuthenticatedContext      |
                 | (tenant_id, project_id, role)  |
                 +---------------+----------------+
                                 |
                                 v
                 +---------------+----------------+
                 |         FastAPI Route          |
                 +--------------------------------+
```

---

## 2. API Key Design & Cryptographic Security

- **Format**: `tg_live_<32-character-urlsafe-secret>`
- **Prefix (`key_prefix`)**: `tg_live_a8f3d91c` (First 16 chars). Used for $O(1)$ indexed database query filtering.
- **Hash (`key_hash`)**: SHA-256 digest (`hashlib.sha256(raw_key).hexdigest()`).
- **Non-Persistence of Raw Secrets**: The complete raw secret is returned **ONLY ONCE** upon API key creation or rotation. Raw keys are NEVER stored in PostgreSQL and are NEVER returned in GET / list endpoints.
- **Constant-Time Verification**: Verification uses `hmac.compare_digest` to prevent timing attacks.

---

## 3. Multi-Tenant Isolation Model

Tollgate enforces strict tenant boundary isolation at every layer:

1. **Context Derivation**: Every API request derives `tenant_id` authoritatively from the validated `AuthenticatedContext`.
2. **Database Schema Constraints**:
   - `projects` table has `FOREIGN KEY (tenant_id) REFERENCES tenants(id)` and `UNIQUE(tenant_id, slug)`.
   - `api_keys` table stores `tenant_id` explicitly alongside `project_id` for instant query filtering.
   - `users` table has `UNIQUE(tenant_id, email)`.
3. **Resource Non-Disclosure Policy**: When an authenticated context attempts to query or mutate a resource (Project, User, API Key) belonging to another tenant, the system returns `404 Not Found` to prevent revealing the existence of cross-tenant resources.

---

## 4. Role-Based Access Control (RBAC)

Tollgate implements centralized permission checks across three roles:

| Role | Permissions & Scope |
| :--- | :--- |
| **OWNER** | Full tenant administration, user management, project creation, API key generation/revocation/rotation. |
| **ADMIN** | Project management, user management, API key generation/revocation/rotation. |
| **VIEWER** | Read-only access to tenant metadata. Cannot mutate users, create projects, or create/revoke API keys. |

---

## 5. Security & Audit Logging Guidelines

- **Zero Secret Exposure**: Raw API keys, passwords, and `Authorization` headers are never logged.
- **Audit Logs**: Security operations emit structured audit logs containing safe identifiers:
  `event`, `tenant_id`, `project_id`, `api_key_id`, `user_id`, and UTC timestamp.
- **Uniform Error Responses**: Authentication failures return a standardized `401 Unauthorized` response (`{"detail": "Invalid or expired API key"}`) regardless of internal cause (key missing, invalid hash, expired, or revoked) to prevent username/key enumeration.
