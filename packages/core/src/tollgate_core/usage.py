import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class UsageEventPayload(BaseModel):
    event_version: int = Field(default=1, description="Schema version of the usage event")
    event_id: UUID = Field(
        default_factory=uuid.uuid4, description="Globally unique event idempotency identifier"
    )
    request_id: str = Field(..., description="Gateway request ID correlated with the HTTP request")
    reservation_id: Optional[str] = Field(None, description="Phase 5 budget reservation ID")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when event occurred",
    )

    tenant_id: UUID = Field(..., description="Tenant ID")
    project_id: UUID = Field(..., description="Project ID")
    api_key_id: Optional[UUID] = Field(None, description="API Key ID")

    provider: str = Field(
        ..., min_length=1, max_length=64, description="Upstream LLM provider name"
    )
    model: str = Field(
        ..., min_length=1, max_length=128, description="Model identifier requested/used"
    )

    stream: bool = Field(
        default=False, description="Whether the request was an SSE streaming completion"
    )
    status: Literal["success", "provider_failure", "client_cancelled"] = Field(
        ..., description="Terminal request execution status"
    )

    input_tokens: int = Field(default=0, ge=0, description="Normalized input tokens consumed")
    output_tokens: int = Field(default=0, ge=0, description="Normalized output tokens generated")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed")

    estimated_cost: int = Field(
        default=0, ge=0, description="Estimated cost in microdollars ($1.00 = 1,000,000)"
    )
    actual_cost: int = Field(default=0, ge=0, description="Actual cost settled in microdollars")

    latency_ms: float = Field(
        default=0.0, ge=0.0, description="End-to-end provider execution latency in ms"
    )
    attempt_count: int = Field(default=1, ge=1, description="Number of provider attempts made")
    fallback_used: bool = Field(default=False, description="Whether fallback route was triggered")

    # Phase 9 Learned Model Router fields (backward-compatible)
    router_mode: Optional[str] = Field(
        default=None, description="Router mode (disabled, static, learned)"
    )
    router_route: Optional[str] = Field(
        default=None, description="Tier selected by router (cheap, strong, passthrough, fallback)"
    )
    router_confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Router confidence score"
    )
    router_model_version: Optional[str] = Field(default=None, description="Router artifact version")
    router_fallback: bool = Field(
        default=False, description="Whether router failed open to fallback"
    )
    original_model: Optional[str] = Field(
        default=None, description="Original model requested before routing"
    )

    @field_validator("event_version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"Unsupported event version: {v}. Only version 1 is supported.")
        return v

    def to_stream_entry(self) -> Dict[str, str]:
        """Convert payload to a Redis Stream dictionary."""
        return {"data": self.model_dump_json()}

    @classmethod
    def from_stream_entry(cls, entry_data: Dict[Union[str, bytes], Any]) -> "UsageEventPayload":
        """Parse stream entry from Redis, supporting either JSON string or dictionary representation."""
        # Convert any bytes keys/values to str
        normalized: Dict[str, Any] = {}
        for k, v in entry_data.items():
            key_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            val_str = v.decode("utf-8") if isinstance(v, bytes) else v
            normalized[key_str] = val_str

        # Check for wrapped JSON in 'data' or 'payload'
        if "data" in normalized and isinstance(normalized["data"], str):
            raw = json.loads(normalized["data"])
            return cls.model_validate(raw)
        if "payload" in normalized and isinstance(normalized["payload"], str):
            raw = json.loads(normalized["payload"])
            return cls.model_validate(raw)

        # Otherwise parse normalized flat dict
        return cls.model_validate(normalized)


class DeadLetterPayload(BaseModel):
    original_event_id: Optional[str] = None
    failure_reason: str
    failure_type: (
        str  # "validation_error", "unsupported_version", "corrupted_payload", "exhausted_retries"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    original_payload: str

    def to_stream_entry(self) -> Dict[str, str]:
        return {"data": self.model_dump_json()}
