import hashlib
import json
from typing import Optional, Tuple
from uuid import UUID

from gateway.src.schemas.chat import ChatCompletionRequest

SEMANTIC_REPRESENTATION_VERSION = "v1"


class SemanticRepresentation:
    """
    Handles deterministic conversation serialization, compatibility fingerprinting,
    and cacheability evaluation for the semantic response cache.
    """

    @classmethod
    def is_cacheable(cls, request: ChatCompletionRequest) -> Tuple[bool, Optional[str]]:
        """
        Determines whether a request is eligible for semantic response caching.
        Bypasses streaming, tool-enabled requests, and multiple completions.
        """
        if request.stream:
            return False, "streaming_not_supported"

        if request.tools is not None and len(request.tools) > 0:
            return False, "tools_present"

        if request.tool_choice is not None and request.tool_choice != "none":
            return False, "tool_choice_present"

        n_val = getattr(request, "n", 1) or 1
        if n_val > 1:
            return False, "multiple_completions_not_supported"

        return True, None

    @classmethod
    def build_text_to_embed(cls, request: ChatCompletionRequest) -> str:
        """
        Builds a deterministic string representation of the conversation suitable for embedding.
        Preserves message order, role boundaries, and message content whitespace.
        """
        parts = []
        for msg in request.messages:
            role = msg.role.strip()
            content = msg.content or ""
            parts.append(f"role={role}\ncontent={content}")
        return "\n\n".join(parts)

    @classmethod
    def compute_fingerprint(
        cls,
        request: ChatCompletionRequest,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
    ) -> str:
        """
        Calculates a deterministic SHA-256 fingerprint representing the generation configuration.
        Ensures requests with different sampling parameters, models, or response formats do not collide.
        """
        # Canonicalize sampling parameters
        temperature = 1.0 if request.temperature is None else round(float(request.temperature), 6)
        top_p = 1.0 if request.top_p is None else round(float(request.top_p), 6)
        seed = request.seed if request.seed is not None else "none"
        max_tokens = request.max_tokens if request.max_tokens is not None else "none"

        response_format = "text"
        if request.response_format is not None:
            if isinstance(request.response_format, dict):
                response_format = request.response_format.get("type", "text")
            elif hasattr(request.response_format, "type"):
                response_format = request.response_format.type

        stop_val = "none"
        if request.stop is not None:
            if isinstance(request.stop, str):
                stop_val = request.stop
            elif isinstance(request.stop, list):
                stop_val = ",".join(sorted(request.stop))

        system_prompts = [str(m.content or "") for m in request.messages if m.role == "system"]
        system_hash = (
            hashlib.sha256("".join(system_prompts).encode("utf-8")).hexdigest()
            if system_prompts
            else "none"
        )

        fingerprint_dict = {
            "version": SEMANTIC_REPRESENTATION_VERSION,
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "provider": provider.strip().lower(),
            "model": request.model.strip().lower(),
            "temperature": temperature,
            "top_p": top_p,
            "seed": seed,
            "max_tokens": max_tokens,
            "stop": stop_val,
            "response_format": response_format,
            "system_hash": system_hash,
        }

        canonical_json = json.dumps(fingerprint_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
