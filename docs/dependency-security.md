# Tollgate Dependency Security & Supply Chain Audit

## 1. Package Manager & Dependency Architecture

Tollgate uses standard Python packaging (`pyproject.toml` with `setuptools` build backend) arranged as a monorepo:
- `tollgate-core`: Shared core library for data models, security utilities (Argon2 / SHA-256), settings, and OpenTelemetry instrumentation.
- `tollgate-gateway`: FastAPI application exposing the OpenAI-compatible gateway and dashboard REST API.
- `tollgate-worker`: Background worker processing usage streams from Redis into PostgreSQL rollups.
- `tollgate-dashboard`: Vite/React frontend dashboard interface (`package.json` with npm).

---

## 2. Security-Sensitive Dependencies Inventory

The following core packages govern authentication, network I/O, database access, cryptography, and proxying:

| Package | Minimum Version | Critical Role / Function | Security Responsibility |
| :--- | :--- | :--- | :--- |
| `fastapi` | `>=0.110.0` | HTTP application framework | Request parsing, dependency injection, routing |
| `pydantic` | `>=2.6.4` | Data validation and schema boundaries | Rejecting malformed payloads, enforcing size constraints |
| `argon2-cffi` | `>=23.1.0` | Password hashing (Argon2id) | Defense against GPU credential cracking |
| `sqlalchemy` | `>=2.0.28` | Database ORM and query builder | Parameterized SQL execution, zero raw SQL injection |
| `asyncpg` | `>=0.29.0` | Asynchronous PostgreSQL driver | Binary protocol communication with PostgreSQL |
| `redis` | `>=5.0.3` | Redis client | Atomic Lua scripts for rate limiting and budgets |
| `urllib3` | `>=2.8.0` | Underlying HTTP client engine | Fixed CVE-2026-97687 and CVE-2026-97689 |
| `httpx` | `>=0.27.0` | Async HTTP client for provider proxies | TLS verification, timeout handling, connection pooling |
| `opentelemetry-*` | `>=1.24.0` | Distributed tracing framework | Sanitized telemetry emission without credential leakage |
| `prometheus-client`| `>=0.20.0`| Metrics scrape exporter | Bounded cardinality metric rendering |

---

## 3. Dependency Vulnerability Audit Tooling

- **Primary Audit Tool**: `pip-audit` (`pip_audit` v2.10.1) using the Python Packaging Advisory Database (PyPA) and OSV (Open Source Vulnerabilities) API.
- **Initial Audit Findings**:
  - `urllib3 2.7.0`: Identified CVE-2026-97687 and CVE-2026-97689.
  - `pip 24.3.1`: Identified advisory vulnerabilities in older packaging toolchain.
- **Mitigation & Resolution**:
  - Upgraded `urllib3` to `2.8.0`.
  - Upgraded `pip` to `26.2.1`.
  - Specified `urllib3>=2.8.0` in root `pyproject.toml`.
  - Re-ran `python -m pip_audit`: Resulted in **0 known vulnerabilities**.

---

## 4. Known Exceptions & Exclusions

1. **Local Editable Packages (`tollgate-core`, `tollgate-gateway`)**:
   - `pip-audit` skips these packages with `"Dependency not found on PyPI and could not be audited"` because they are local workspace monorepo packages. Their third-party sub-dependencies are audited transitively.
2. **Database Engine**:
   - SQLite (`aiosqlite`) is included exclusively in `dev` dependencies for fast, isolated unit test execution. Production environments run exclusively against PostgreSQL (`asyncpg`).

---

## 5. Lock-File Strategy & Dependency Update Policy

1. **Lock-File Strategy**:
   - Production Docker images pin direct packages and build wheels in isolated stages.
   - For CI/CD and deployment pipelines, dependencies are verified against strict vulnerability scanners before production deployment.
2. **Update Policy**:
   - Security patches: Applied within 48 hours of disclosure following automated test suite verification.
   - Minor/Major updates: Audited monthly. Dependency updates are never applied blindly; each update must pass unit, integration, and security test suites (`pytest tests/security/`), static analysis (`ruff`), and container build validation.

> [!IMPORTANT]
> Dependency scanning against vulnerability databases detects known publicly reported CVEs. It does not prove that an application or its third-party dependencies are free from undiscovered zero-day vulnerabilities.
