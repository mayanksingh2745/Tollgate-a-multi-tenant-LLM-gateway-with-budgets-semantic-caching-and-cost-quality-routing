# Tollgate Security Test Matrix

This matrix documents the comprehensive application and boundary security test suite implemented in `tests/security/`. Every test listed below has been executed and verified in the automated test suite.

| Area | Attack / Threat | Expected Result | Test Name | Status |
| :--- | :--- | :--- | :--- | :---: |
| **Authentication** | Valid API key Bearer authentication | HTTP 200 with completion payload | `tests/security/test_auth_security.py::test_auth_valid_key` | **PASS** |
| **Authentication** | Missing Authorization header | HTTP 401 with generic error envelope | `tests/security/test_auth_security.py::test_auth_missing_header` | **PASS** |
| **Authentication** | Malformed Authorization header (e.g. Basic, Bearer without token, extra spaces) | HTTP 401 without stack trace | `tests/security/test_auth_security.py::test_auth_malformed_headers` | **PASS** |
| **Authentication** | Wrong prefix or invalid key entropy probing | HTTP 401 with normalized message | `tests/security/test_auth_security.py::test_auth_wrong_prefix_and_invalid_keys` | **PASS** |
| **Authentication** | Revoked API key authentication attempt | HTTP 401 `"Invalid or expired API key"` | `tests/security/test_auth_security.py::test_auth_revoked_key` | **PASS** |
| **Authentication** | Expired API key authentication attempt | HTTP 401 `"Invalid or expired API key"` | `tests/security/test_auth_security.py::test_auth_expired_key` | **PASS** |
| **Authentication** | Disabled / suspended tenant or project key authentication | HTTP 401 denial | `tests/security/test_auth_security.py::test_auth_disabled_tenant_and_project` | **PASS** |
| **Authentication** | Key rotation invalidation (old key authentication attempt) | Old key returns 401, new key returns 200 | `tests/security/test_auth_security.py::test_auth_rotated_key` | **PASS** |
| **Authentication** | Key hash harvesting via list endpoints | Keys return only prefix; raw key and hashes never returned | `tests/security/test_auth_security.py::test_auth_no_hash_or_credential_leakage` | **PASS** |
| **RBAC** | Owner and Admin administrative actions (key creation, budget update, cache purge) | Permitted (HTTP 200 / 201) | `tests/security/test_rbac_security.py::test_rbac_owner_and_admin_capabilities` | **PASS** |
| **RBAC** | Viewer role attempting mutation (create key, update budget, delete cache, create project) | HTTP 403 Forbidden server-side denial | `tests/security/test_rbac_security.py::test_rbac_viewer_denied_mutations` | **PASS** |
| **RBAC** | Viewer role accessing read-only telemetry and dashboard | HTTP 200 permitted for overview, costs, models, requests | `tests/security/test_rbac_security.py::test_rbac_viewer_allowed_read_telemetry` | **PASS** |
| **RBAC** | Unauthenticated caller accessing protected management routes | HTTP 401 Unauthorized | `tests/security/test_rbac_security.py::test_rbac_unauthorized_access` | **PASS** |
| **Tenant Isolation** | Tenant A attempting to retrieve Tenant B project metadata | HTTP 404 Not Found (safe not-found) | `tests/security/test_tenant_isolation_security.py::test_cross_tenant_project_isolation` | **PASS** |
| **Tenant Isolation** | Tenant A attempting to list or create keys in Tenant B project | HTTP 404 Not Found | `tests/security/test_tenant_isolation_security.py::test_cross_tenant_api_key_isolation` | **PASS** |
| **Tenant Isolation** | Tenant A attempting to view or modify Tenant B budgets | HTTP 404 Not Found | `tests/security/test_tenant_isolation_security.py::test_cross_tenant_budget_isolation` | **PASS** |
| **Tenant Isolation** | Tenant A attempting to invalidate Tenant B project cache | HTTP 403 / 404 denial | `tests/security/test_tenant_isolation_security.py::test_cross_tenant_cache_invalidation_isolation` | **PASS** |
| **Tenant Isolation** | Tenant A querying usage supplying Tenant B tenant_id filter | HTTP 403 / 404 Access Denied | `tests/security/test_tenant_isolation_security.py::test_cross_tenant_usage_and_rollups_isolation` | **PASS** |
| **Tenant Isolation** | Tenant A requesting specific request_id executed by Tenant B | HTTP 404 Request not found or access denied | `tests/security/test_tenant_isolation_security.py::test_cross_tenant_dashboard_request_detail_isolation` | **PASS** |
| **IDOR / BOLA** | Tampered tenant_id in usage event query parameters | HTTP 403 Access Denied | `tests/security/test_idor_security.py::test_idor_tampered_tenant_in_usage_query` | **PASS** |
| **IDOR / BOLA** | Tampered project_id in usage query parameters | HTTP 403 Access Denied | `tests/security/test_idor_security.py::test_idor_tampered_project_in_usage_query` | **PASS** |
| **IDOR / BOLA** | Tampered tenant_id in PUT /tenants/{id}/budget path | HTTP 404 Tenant not found | `tests/security/test_idor_security.py::test_idor_tampered_tenant_in_budget_endpoints` | **PASS** |
| **IDOR / BOLA** | Tampered project_id in GET /projects/{id}/budget path | HTTP 404 Project not found | `tests/security/test_idor_security.py::test_idor_tampered_project_in_budget_endpoints` | **PASS** |
| **IDOR / BOLA** | Tampered project_id filter in dashboard overview | HTTP 404 Project not found or not in tenant | `tests/security/test_idor_security.py::test_idor_dashboard_filter_tampering` | **PASS** |
| **Request Validation** | Excessive message array count (> 1000 messages) | HTTP 400 Invalid Request | `tests/security/test_request_validation_security.py::test_validation_excessive_message_count` | **PASS** |
| **Request Validation** | Oversized individual message content (> 500k characters) | HTTP 400 Invalid Request | `tests/security/test_request_validation_security.py::test_validation_oversized_message_content` | **PASS** |
| **Request Validation** | Excessive requested max_tokens (> 128,000 or negative) | HTTP 400 Invalid Request before execution | `tests/security/test_request_validation_security.py::test_validation_excessive_max_tokens` | **PASS** |
| **Request Validation** | Enormous tool definitions (> 64 tools or name > 64 chars) | HTTP 400 Invalid Request | `tests/security/test_request_validation_security.py::test_validation_excessive_tool_definitions` | **PASS** |
| **Request Validation** | Empty model string or unexpected injected JSON fields | HTTP 400 Invalid Request (`extra='forbid'`) | `tests/security/test_request_validation_security.py::test_validation_invalid_model_and_unknown_fields` | **PASS** |
| **Exact Cache** | Cross-tenant cache hit attempt on identical prompt | HTTP 200 with `X-Tollgate-Cache: MISS` (isolated cache key) | `tests/security/test_cache_security.py::test_exact_cache_cross_tenant_isolation` | **PASS** |
| **Exact Cache** | Generation parameter modification (temperature, stop, max_tokens) | `X-Tollgate-Cache: MISS` | `tests/security/test_cache_security.py::test_exact_cache_parameter_differentiation` | **PASS** |
| **Cache Poisoning** | Storing streaming or tool-call responses in cache | `X-Tollgate-Cache: BYPASS` (streaming/tool calls never cached) | `tests/security/test_cache_security.py::test_cache_poisoning_bypass_for_streaming_and_tools` | **PASS** |
| **Semantic Cache** | Adversarial prompt with differing system instruction | `X-Tollgate-Cache: MISS` (system_hash in fingerprint prevents collision) | `tests/security/test_cache_security.py::test_semantic_cache_system_instruction_isolation` | **PASS** |
| **Budget Security** | Negative budget update or integer overflow (> 1e15) | HTTP 400 / 422 Bad Request | `tests/security/test_budget_security.py::test_budget_negative_and_overflow_values_rejected` | **PASS** |
| **Budget Security** | Replayed / duplicate settlement on reservation | Idempotent no-op; refund not duplicated | `tests/security/test_budget_security.py::test_budget_idempotent_settlement` | **PASS** |
| **Budget Security** | Client sending forged zero-cost headers | Client headers ignored; server computes actual cost | `tests/security/test_budget_security.py::test_budget_client_cannot_forge_cost` | **PASS** |
| **SQL Injection** | SQL payloads in dashboard request search (`' OR '1'='1`, `UNION SELECT`) | Safely parameterized; HTTP 200 with zero injection | `tests/security/test_sql_injection_security.py::test_sql_injection_dashboard_search` | **PASS** |
| **SQL Injection** | SQL injection in dashboard `sort_by` or `sort_order` | Whitelisted fallback column; HTTP 200 | `tests/security/test_sql_injection_security.py::test_sql_injection_dashboard_sorting` | **PASS** |
| **SQL Injection** | SQL payloads in model, provider, or status filters | Parameterized SQLAlchemy query; HTTP 200 | `tests/security/test_sql_injection_security.py::test_sql_injection_dashboard_filters` | **PASS** |
| **Error Leakage** | Unhandled internal exception or DB crash | HTTP 500 OpenAI envelope without stack trace or secrets | `tests/security/test_error_and_telemetry_leakage.py::test_unhandled_exception_sanitization` | **PASS** |
| **Telemetry Leakage** | Confidential customer prompt in OpenTelemetry span attributes | Redacted / omitted; prompt not found in trace attributes | `tests/security/test_error_and_telemetry_leakage.py::test_opentelemetry_trace_sanitization` | **PASS** |
| **Telemetry Leakage** | Sensitive keys (`password`, `authorization`, `prompt`, `embedding`, `tg_live_...`) | Blocked or redacted by `safe_set_attribute` | `tests/security/test_error_and_telemetry_leakage.py::test_safe_set_attribute_redacts_sensitive_patterns` | **PASS** |
