import json
import logging
from typing import AsyncIterator

import httpx
from gateway.src.providers.base import (
    LLMProvider,
    ProviderAuthenticationError,
    ProviderException,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from gateway.src.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)

logger = logging.getLogger("tollgate.provider.openai_compatible")


class OpenAICompatibleProvider(LLMProvider):
    """
    Adapter for any OpenAI-compatible LLM endpoint
    (OpenAI, OpenRouter, Together, vLLM, Ollama, etc.).
    """

    def __init__(
        self,
        name: str = "openai_compatible",
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        timeout: float = 60.0,
    ):
        super().__init__(name=name, base_url=base_url.rstrip("/"), api_key=api_key, timeout=timeout)

    def _build_headers(self, request_id: str) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_payload(
        self, request: ChatCompletionRequest, resolved_model: str, stream: bool
    ) -> dict:
        payload = {
            "model": resolved_model,
            "messages": [m.model_dump(exclude_none=True) for m in request.messages],
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.stop is not None:
            payload["stop"] = request.stop
        if request.presence_penalty is not None:
            payload["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            payload["frequency_penalty"] = request.frequency_penalty
        if request.response_format is not None:
            payload["response_format"] = request.response_format.model_dump()
        return payload

    async def chat(
        self,
        request: ChatCompletionRequest,
        resolved_model: str,
        request_id: str,
    ) -> ChatCompletionResponse:
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers(request_id)
        payload = self._build_payload(request, resolved_model, stream=False)

        timeout_cfg = httpx.Timeout(self.timeout, connect=10.0)

        try:
            async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                res = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as e:
            logger.warning(f"Provider {self.name} timeout on request {request_id}: {e}")
            raise ProviderTimeoutError(
                f"Provider {self.name} timed out after {self.timeout}s"
            ) from e
        except httpx.RequestError as e:
            logger.error(f"Provider {self.name} network failure on request {request_id}: {e}")
            raise ProviderException(f"Provider {self.name} network connection error: {e}") from e

        if res.status_code == 401 or res.status_code == 403:
            raise ProviderAuthenticationError(
                f"Provider {self.name} authentication failed (HTTP {res.status_code})"
            )
        elif res.status_code == 429:
            raise ProviderRateLimitError(f"Provider {self.name} rate limit exceeded")
        elif res.status_code >= 400:
            raise ProviderException(
                f"Provider {self.name} returned error status {res.status_code}: {res.text}",
                status_code=502,
            )

        try:
            data = res.json()
            return ChatCompletionResponse.model_validate(data)
        except Exception as e:
            logger.error(f"Failed to parse provider response on request {request_id}: {e}")
            raise ProviderException(f"Malformed response from provider {self.name}") from e

    async def stream(
        self,
        request: ChatCompletionRequest,
        resolved_model: str,
        request_id: str,
    ) -> AsyncIterator[ChatCompletionChunk]:
        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers(request_id)
        payload = self._build_payload(request, resolved_model, stream=True)

        timeout_cfg = httpx.Timeout(self.timeout, connect=10.0)

        async with httpx.AsyncClient(timeout=timeout_cfg) as client:
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code == 401 or response.status_code == 403:
                        raise ProviderAuthenticationError(
                            f"Provider {self.name} authentication failed"
                        )
                    elif response.status_code == 429:
                        raise ProviderRateLimitError(f"Provider {self.name} rate limit exceeded")
                    elif response.status_code >= 400:
                        content = await response.aread()
                        raise ProviderException(
                            f"Provider {self.name} stream error {response.status_code}: {content.decode('utf-8', errors='ignore')}"
                        )

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk_json = json.loads(data_str)
                                yield ChatCompletionChunk.model_validate(chunk_json)
                            except Exception as parse_err:
                                logger.warning(f"Ignoring unparseable SSE chunk: {parse_err}")
                                continue
            except httpx.TimeoutException as e:
                logger.warning(f"Provider {self.name} stream timeout on {request_id}: {e}")
                raise ProviderTimeoutError(f"Provider {self.name} stream timed out") from e
            except httpx.RequestError as e:
                logger.error(f"Provider {self.name} stream network error on {request_id}: {e}")
                raise ProviderException(f"Provider {self.name} stream error: {e}") from e
