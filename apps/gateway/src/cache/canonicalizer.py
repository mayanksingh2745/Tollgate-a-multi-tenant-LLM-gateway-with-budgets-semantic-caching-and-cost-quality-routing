import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from gateway.src.config import settings
from gateway.src.schemas.chat import ChatCompletionRequest


class Canonicalizer:
    """
    Builds deterministic canonical request representations and computes SHA-256 cache keys.
    Enforces tenant, project, provider, and model isolation.
    """

    @staticmethod
    def is_cacheable(request: ChatCompletionRequest) -> Tuple[bool, Optional[str]]:
        """
        Determines if a request satisfies the cacheability policy.
        Returns (True, None) if cacheable, or (False, reason) if bypassed.
        """
        if not settings.cache_enabled:
            return False, "cache_disabled"

        # Section 5: Streaming requests bypass cache
        if request.stream:
            return False, "streaming_bypass"

        # Section 17: Tool and function requests bypass cache to prevent side-effect replay
        if getattr(request, "tools", None) or getattr(request, "tool_choice", None):
            return False, "tools_bypass"

        return True, None

    @staticmethod
    def build_canonical_dict(
        request: ChatCompletionRequest,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
    ) -> Dict[str, Any]:
        """
        Extracts all cache-relevant parameters into a normalized dictionary.
        Preserves message order and exact content semantics.
        Distinguishes omitted parameters (None) from explicit defaults (e.g., temperature=0).
        """
        # Canonicalize messages preserving exact order, content, and role
        canonical_messages: List[Dict[str, Any]] = []
        for msg in request.messages:
            msg_dict: Dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.name is not None:
                msg_dict["name"] = msg.name
            canonical_messages.append(msg_dict)

        canonical: Dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "provider": provider.strip().lower(),
            "model": request.model.strip().lower(),
            "messages": canonical_messages,
        }

        # Include generation controls only when explicitly specified
        if request.temperature is not None:
            canonical["temperature"] = float(request.temperature)
        if request.top_p is not None:
            canonical["top_p"] = float(request.top_p)
        if request.max_tokens is not None:
            canonical["max_tokens"] = int(request.max_tokens)
        if request.stop is not None:
            if isinstance(request.stop, str):
                canonical["stop"] = [request.stop]
            else:
                canonical["stop"] = list(request.stop)
        if request.presence_penalty is not None:
            canonical["presence_penalty"] = float(request.presence_penalty)
        if request.frequency_penalty is not None:
            canonical["frequency_penalty"] = float(request.frequency_penalty)
        if getattr(request, "seed", None) is not None:
            canonical["seed"] = int(request.seed)
        if request.response_format is not None:
            canonical["response_format"] = {"type": request.response_format.type}
        if getattr(request, "user", None) is not None:
            canonical["user"] = str(request.user)

        return canonical

    @classmethod
    def compute_hash(
        cls,
        request: ChatCompletionRequest,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
    ) -> str:
        """
        Computes SHA-256 digest of the canonical request dictionary using deterministic JSON serialization.
        """
        canonical_dict = cls.build_canonical_dict(
            request=request,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
        )
        serialized = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
