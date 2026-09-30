# Learned Model Router (Phase 9)

## Overview

The **Learned Model Router** in Tollgate is a data-driven model selection layer that dynamically routes requests between a cost-effective, high-throughput model (e.g. `mock-fast`, `gpt-4o-mini`) and a stronger reasoning model (e.g. `mock-model`, `gpt-4o`, `claude-3-5-sonnet`).

The router is designed with strict production engineering guarantees:
- **Measurable**: Real-time latency tracking and routing metrics.
- **Deterministic**: Versioned feature schema and model artifacts with reproducible inference.
- **Explainable**: Features and decision thresholds are interpretable (`StandardScaler` + `LogisticRegression`).
- **Cost-Aware**: Integrates with Tollgate's microdollar pricing service to calculate real economic savings.
- **Fail-Open**: Single points of failure are prevented; missing artifacts, feature extraction errors, or timeouts fall back gracefully to the original or configured fallback model.
- **Disabled by Default**: Preserves pre-Phase 9 behavior unless explicitly enabled.

---

## Architecture & Request Pipeline

The router intercepts requests after cache evaluation and before atomic budget reservation:

```text
Client Request
      ↓
Authentication & API Key Verification
      ↓
Distributed Rate Limiting
      ↓
Exact Response Cache Lookup (Phase 7)
      ├─ HIT  → Return cached response (0ms router overhead)
      └─ MISS ↓
Semantic Response Cache Lookup (Phase 8)
      ├─ HIT  → Return cached response (0ms router overhead)
      └─ MISS ↓
Model Router (Phase 9)
      ├─ Disabled   → Passthrough to original request model
      ├─ Static     → Route to configured static model
      └─ Learned    → Extract features → Classifier inference → Threshold decision
                       ├─ Shadow Mode: log decision & metrics, preserve original model
                       └─ Active Mode: rewrite request.model to selected tier
      ↓
Atomic Budget Reservation (Phase 5)
      (Calculated on the actual selected model tier)
      ↓
Provider Reliability, Retries & Fallback (Phase 3)
      ↓
Upstream Provider Execution
      ↓
Cache Storage & Semantic Indexing (Phases 7 & 8)
      ↓
Asynchronous Usage Event Pipeline (Phase 6)
      (Enriched with router mode, route, confidence, and model version)
```

---

## Feature Extraction

The router uses 15 structural and lexical signals extracted from the incoming `ChatCompletionRequest` before calling any provider:

| Feature Name | Description | Rationale |
|---|---|---|
| `token_count_estimate` | Approximate tokens (~chars/4) | Longer prompts often require stronger models |
| `char_count` | Total characters across all messages | Raw prompt size indicator |
| `message_count` | Number of messages in conversation | Dialogue structure |
| `user_turn_count` | Number of user messages | Multi-turn indicator |
| `system_message_count` | Number of system messages | Instruction overhead |
| `avg_message_length` | Mean length per message | Message verbosity |
| `max_message_length` | Maximum length among messages | Outlier long context detection |
| `question_mark_count` | Count of `?` characters | Number of direct inquiries |
| `has_code_block` | Binary flag for ``` code blocks | Technical code generation/refactoring |
| `has_json_structure` | Binary flag for JSON formatting | Structured data extraction/validation |
| `has_sql_keywords` | Binary flag for SQL syntax | Database querying complexity |
| `has_math_symbols` | Binary flag for arithmetic/math symbols | Mathematical/algebraic reasoning |
| `has_url` | Binary flag for HTTP/HTTPS URLs | Web context retrieval tasks |
| `conversation_depth` | User ↔ Assistant turn transitions | Deep multi-turn context |
| `last_user_message_length` | Length of most recent user message | Current instruction scope |

---

## Routing Modes

1. **Disabled (`disabled`)** [Default]:
   Passthrough mode. Requests are served by their originally requested model. Zero ML inference overhead.
2. **Static (`static`)**:
   Always routes to `TOLLGATE_ROUTER_STRONG_MODEL` (or specified static model). Useful for A/B testing, gradual cutovers, and baseline benchmarking.
3. **Learned (`learned`)**:
   Loads the trained model artifact (`model.joblib`) and validates schema versioning (`metadata.json`).
   - If `confidence >= TOLLGATE_ROUTER_QUALITY_THRESHOLD`: routes to `cheap_model`.
   - Else: routes to `strong_model`.
   - In **Shadow Mode** (`TOLLGATE_ROUTER_SHADOW_MODE=true`), the decision is logged and recorded in metrics and response headers, but `request.model` is not modified.

---

## Configuration Settings

| Environment Variable | Default | Description |
|---|---|---|
| `TOLLGATE_ROUTER_ENABLED` | `false` | Master toggle for model router |
| `TOLLGATE_ROUTER_MODE` | `"disabled"` | Routing mode (`disabled`, `static`, `learned`) |
| `TOLLGATE_ROUTER_SHADOW_MODE` | `false` | When true, evaluates decisions without rewriting models |
| `TOLLGATE_ROUTER_CHEAP_MODEL` | `"mock-fast"` | Identifier for cost-efficient model |
| `TOLLGATE_ROUTER_STRONG_MODEL` | `"mock-model"` | Identifier for high-capability reasoning model |
| `TOLLGATE_ROUTER_QUALITY_THRESHOLD` | `0.70` | Confidence threshold for selecting cheap model |
| `TOLLGATE_ROUTER_FALLBACK_MODEL` | `None` | Fallback model if router fails open (defaults to original) |
| `TOLLGATE_ROUTER_MODEL_VERSION` | `None` | Expected artifact model version for validation |
| `TOLLGATE_ROUTER_ARTIFACT_PATH` | `None` | Path to directory containing `model.joblib` and `metadata.json` |
| `TOLLGATE_ROUTER_MAX_QUALITY_DEGRADATION` | `0.05` | Maximum allowable false positive rate during threshold tuning |

---

## Observability & Response Headers

When the router is active, Tollgate emits informative debugging headers:

- `X-Tollgate-Router-Route`: Selected tier (`cheap`, `strong`, `static`, `fallback`, `passthrough`).
- `X-Tollgate-Router-Selected-Model`: Final model identifier selected.
- `X-Tollgate-Router-Confidence`: Confidence score between 0.0000 and 1.0000.
- `X-Tollgate-Router-Shadow`: Set to `true` if decision was evaluated in shadow mode.
- `X-Tollgate-Router-Fallback`: Set to `true` if router encountered an error and failed open.
