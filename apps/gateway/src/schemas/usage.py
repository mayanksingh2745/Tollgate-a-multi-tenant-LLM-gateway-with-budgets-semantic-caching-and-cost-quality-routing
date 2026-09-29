from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UsageEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    event_version: int
    request_id: str
    reservation_id: Optional[str] = None
    tenant_id: UUID
    project_id: UUID
    api_key_id: Optional[UUID] = None
    provider: str
    model: str
    stream: bool
    status: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: int
    actual_cost: int
    latency_ms: float
    attempt_count: int
    fallback_used: bool
    created_at: datetime
    processed_at: datetime


class PaginatedUsageResponse(BaseModel):
    items: List[UsageEventResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False


class UsageDailyRollupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    date: str
    tenant_id: UUID
    project_id: UUID
    provider: str
    model: str
    request_count: int
    success_count: int
    failure_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: int
    actual_cost: int
    updated_at: datetime


class UsageMonthlyRollupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    month: str
    tenant_id: UUID
    project_id: UUID
    provider: str
    model: str
    request_count: int
    success_count: int
    failure_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: int
    actual_cost: int
    updated_at: datetime
