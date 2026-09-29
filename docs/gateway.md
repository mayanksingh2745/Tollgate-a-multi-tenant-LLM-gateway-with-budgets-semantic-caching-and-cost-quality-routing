# Tollgate OpenAI-Compatible LLM Gateway

Tollgate Phase 2 establishes a high-performance, modular OpenAI-compatible gateway that acts as a secure, tenant-isolated reverse proxy between client applications and downstream LLM providers.

---

## 1. Gateway Architecture

```
                    ┌────────────────────────┐
                    │      Client App        │
                    │ (OpenAI SDK / HTTP)    │
                    └───────────┬────────────┘
                                │
             POST /v1/chat/completions (Bearer tg_live_...)
                                │
                                ▼
                    ┌────────────────────────┐
                    │     FastAPI Router     │
                    │ (/v1/chat/completions) │
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │   Phase 1 API Key Auth │
                    │ (Resolves Tenant & Proj)
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │    Gateway Service     │
                    │ (Model Resolution & ID)│
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │   Provider Interface   │
                    │     (LLMProvider)      │
                    └───────────┬────────────┘
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
     ┌──────────────────────┐        ┌──────────────────────┐
     │ OpenAI Compatible    │        │    Mock Provider     │
     │   HTTP Adapter       │        │ (Tests & Benchmarks) │
     └──────────┬───────────┘        └──────────────────────┘
                │
                ▼
     ┌──────────────────────┐
     │ Upstream Provider    │
     │ (OpenAI, vLLM, etc.) │
     └──────────────────────┘
```

For streaming responses:

```
Client  <=== [text/event-stream] ===  Gateway  <=== [SSE Chunks] ===  LLM Provider
```

---

## 2. Supported Parameters

Tollgate supports standard OpenAI Chat Completion request parameters:

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `model` | `string` | **Yes** | Client model identifier (e.g. `gpt-4o-mini`, `mock-model`) |
| `messages` | `array` | **Yes** | Array of message objects (`role`, `content`, optional `name`) |
| `stream` | `boolean` | No (default `false`) | If `true`, returns Server-Sent Events (SSE) |
| `temperature` | `float` | No | Sampling temperature between `0.0` and `2.0` |
| `top_p` | `float` | No | Nucleus sampling probability between `0.0` and `1.0` |
| `max_tokens` | `integer` | No | Maximum completion tokens to generate |
| `stop` | `string \| list` | No | Stop sequences |
| `presence_penalty` | `float` | No | Penalty between `-2.0` and `2.0` |
| `frequency_penalty`| `float` | No | Penalty between `-2.0` and `2.0` |
| `response_format` | `object` | No | e.g. `{"type": "json_object"}` or `{"type": "text"}` |

---

## 3. Authentication & Tenant Context

Every request must include a Phase 1 Tollgate API key:

```http
Authorization: Bearer tg_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Tollgate extracts the tenant and project context directly from the validated API key. Tenant identity is never accepted from the request body or headers.

---

## 4. Usage Examples

### Python (using official OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    api_key="tg_live_your_tollgate_api_key_here",
    base_url="http://localhost:8000/v1"
)

# 1. Non-streaming completion
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Explain quantum computing briefly"}],
    stream=False
)
print(response.choices[0].message.content)

# 2. Streaming completion
stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Count from 1 to 5"}],
    stream=True
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### cURL (HTTP REST)

```bash
# Non-streaming
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer tg_live_your_tollgate_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'

# Streaming
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer tg_live_your_tollgate_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Stream response"}],
    "stream": true
  }'
```

---

## 5. Request IDs & Observability

- Every request is tagged with a unique request ID.
- Clients can provide `X-Request-ID` in the request header, or Tollgate will automatically generate `req_<uuid>`.
- The request ID is returned in the response header `X-Request-ID`.
- Structured server logs track: `request_id`, `tenant_id`, `project_id`, `api_key_id`, `model`, `provider`, `stream`, `latency_ms`, and `status`. Prompts, completions, and secrets are never logged.

---

## 6. Error Handling

All gateway errors adhere to OpenAI-compatible error payloads:

```json
{
  "error": {
    "message": "The model 'unknown-model' does not exist or is not configured.",
    "type": "invalid_request_error",
    "param": null,
    "code": "model_not_found"
  }
}
```

HTTP Status Codes:
- `400`: Validation error / unsupported parameters
- `401`: Missing or invalid API key
- `404`: Model not found
- `429`: Upstream provider rate limit
- `502`: Upstream provider connection error or failure
- `504`: Upstream provider timeout
