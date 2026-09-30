# Incident Response Playbook (Phase 14)

## Overview

This document specifies operational response procedures for common security incidents involving the Tollgate LLM Gateway.

---

## 1. Scenario A: Leaked Tollgate API Key

An active Tollgate client API key (`tg_live_...`) is discovered in a public repository, commit, or unauthorized client log.

### Step-by-Step Response Procedure:
1. **Revoke the Compromised Key**:
   - Immediately update the key's status in PostgreSQL:
     ```sql
     UPDATE api_keys 
     SET is_active = FALSE, updated_at = NOW() 
     WHERE key_prefix = 'tg_live_<prefix>';
     ```
   - Invalidate any in-memory or Redis key caches to ensure immediate rejection.
2. **Issue Replacement Key**:
   - Generate a new key for the affected tenant/project via the admin dashboard or API (`POST /api/v1/projects/{project_id}/keys`).
   - Securely distribute the new raw key to the authorized tenant administrator.
3. **Inspect Affected Usage & Budgets**:
   - Query the usage events and metrics for the compromised `api_key_id` over the incident window:
     ```sql
     SELECT COUNT(*), SUM(total_tokens), SUM(cost) 
     FROM usage_events 
     WHERE api_key_id = '<key_uuid>' AND timestamp >= '<leak_time>';
     ```
   - Check if project budget limits were breached. If fraudulent requests consumed budget, issue a compensating credit in the project's balance.
4. **Audit Gateway Logs**:
   - Search structured logs for `key_id=<key_uuid>` to enumerate all IPs, user agents, and timestamps associated with the unauthorized traffic.
5. **Identify Affected Tenant & Post-Mortem**:
   - Notify the tenant security contact.
   - Document root cause (e.g., hardcoded client credential, unsecured client repository).

---

## 2. Scenario B: Leaked Upstream Provider Credential

An upstream model provider API key (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) is compromised or exposed.

### Step-by-Step Response Procedure:
1. **Rotate the Provider Credential**:
   - Log into the provider management console (OpenAI, Anthropic, etc.) and generate a new API key.
2. **Deploy New Credential to Tollgate**:
   - Update the secret in the production environment / secrets manager.
   - Trigger a rolling restart of Tollgate gateway and worker containers to pick up the new secret.
3. **Invalidate the Old Provider Credential**:
   - Return to the provider console and delete/revoke the compromised key.
   - Verify that Tollgate continues serving traffic successfully using the new credential.
4. **Audit Upstream Provider Usage**:
   - Inspect the upstream provider's usage dashboards for unexpected traffic spikes or unauthorized model queries originating outside of Tollgate's egress IPs.
   - Set up billing alerts on the provider account.

---

## 3. Scenario C: Tenant Isolation / BOLA Vulnerability

A bug or regression allows Tenant A to read, modify, or infer data belonging to Tenant B.

### Step-by-Step Response Procedure:
1. **Restrict Affected Endpoint**:
   - If an endpoint exposes cross-tenant data, temporarily disable or rate-limit the route via reverse-proxy rules (e.g. NGINX block) or emergency deployment.
2. **Preserve Forensic Evidence**:
   - Capture gateway application logs, database WAL logs, and Redis audit trails covering the incident window. Do not rotate or truncate logs.
3. **Identify Affected Tenants**:
   - Parse request logs for calls hitting the vulnerable endpoint. Extract `tenant_id` from the caller context and the targeted resource IDs from the request URL/body.
   - Establish which tenants experienced unauthorized cross-tenant data access.
4. **Develop and Verify Patch**:
   - Implement strict tenant validation (`tenant_id == auth_context.tenant_id`) or fix the faulty join.
   - Add a regression test under `tests/security/` reproducing the exact breach attempt to confirm it returns HTTP 403/404.
5. **Execute Regression Testing**:
   - Run the complete security test suite:
     ```bash
     python -m pytest tests/security/
     ```
6. **Deploy & Post-Incident Review**:
   - Deploy hotfix to production.
   - Conduct post-incident notification to affected tenant administrators in accordance with SLA and data privacy obligations.
