"""Pydantic response and query schemas for the Tollgate Tenant Dashboard API."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class OverviewResponse(BaseModel):
    period: TimeRange
    total_requests: int
    total_tokens: int
    input_tokens: int
    output_tokens: int
    estimated_cost_microdollars: int
    actual_cost_microdollars: int
    estimated_cost_usd: float
    actual_cost_usd: float
    provider_failures: int
    error_rate: float
    cache_hits: int
    cache_hit_rate: float
    exact_cache_hits: int
    semantic_cache_hits: int
    cheap_routing_percentage: float
    strong_routing_percentage: float
    active_models_count: int
    active_providers_count: int


class UsagePoint(BaseModel):
    timestamp: str  # ISO string or YYYY-MM-DD / YYYY-MM-DD HH:00
    requests: int
    tokens: int
    input_tokens: int
    output_tokens: int
    cost_microdollars: int
    cost_usd: float
    success_count: int
    failure_count: int


class UsageSeriesResponse(BaseModel):
    interval: str  # "hour" | "day"
    points: List[UsagePoint]


class CostBreakdownItem(BaseModel):
    name: str
    cost_microdollars: int
    cost_usd: float
    percentage: float
    request_count: int
    total_tokens: int


class CostAnalyticsResponse(BaseModel):
    total_cost_microdollars: int
    total_cost_usd: float
    input_cost_microdollars: int
    output_cost_microdollars: int
    by_model: List[CostBreakdownItem]
    by_provider: List[CostBreakdownItem]
    by_project: List[CostBreakdownItem]


class BudgetStatus(BaseModel):
    monthly_budget_microdollars: Optional[int] = None
    daily_budget_microdollars: Optional[int] = None
    monthly_spent_microdollars: int = 0
    daily_spent_microdollars: int = 0
    monthly_utilization: float = 0.0
    daily_utilization: float = 0.0
    monthly_remaining_microdollars: Optional[int] = None
    daily_remaining_microdollars: Optional[int] = None


class ProjectBudgetStatus(BaseModel):
    project_id: UUID
    project_name: str
    monthly_budget_microdollars: Optional[int] = None
    daily_budget_microdollars: Optional[int] = None
    monthly_spent_microdollars: int = 0
    daily_spent_microdollars: int = 0
    monthly_utilization: float = 0.0
    daily_utilization: float = 0.0
    monthly_remaining_microdollars: Optional[int] = None


class BudgetsOverviewResponse(BaseModel):
    tenant_budget: BudgetStatus
    projects: List[ProjectBudgetStatus]


class ModelAnalyticsItem(BaseModel):
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_microdollars: int
    cost_usd: float
    avg_latency_ms: float
    error_rate: float


class ProviderAnalyticsItem(BaseModel):
    provider: str
    requests: int
    failures: int
    retries: int
    fallbacks: int
    avg_latency_ms: float
    error_rate: float
    fallback_rate: float


class CacheAnalyticsResponse(BaseModel):
    exact_hits: int
    exact_misses: int
    exact_hit_rate: float
    semantic_hits: int
    semantic_misses: int
    semantic_hit_rate: float
    overall_hit_rate: float
    total_cache_hits: int
    estimated_calls_avoided: int
    estimated_cost_avoided_microdollars: int
    estimated_cost_avoided_usd: float
    cache_lookup_errors: int
    cache_write_errors: int
    semantic_cache_errors: int
    semantic_entries_count: int


class RouterAnalyticsResponse(BaseModel):
    router_mode: str
    cheap_selections: int
    strong_selections: int
    passthrough_selections: int
    fallbacks: int
    errors: int
    cheap_percentage: float
    strong_percentage: float
    avg_confidence: float
    router_cheap_provider_strong: int
    offline_evaluation: Optional[Dict[str, Any]] = None


class RequestSummaryItem(BaseModel):
    request_id: str
    created_at: datetime
    project_id: UUID
    project_name: str
    model: str
    provider: str
    status: str
    latency_ms: float
    total_tokens: int
    actual_cost_microdollars: int
    actual_cost_usd: float
    router_route: Optional[str] = None
    cache_status: Optional[str] = None


class PaginatedRequestsResponse(BaseModel):
    items: List[RequestSummaryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class RequestDetailResponse(BaseModel):
    request_id: str
    event_id: UUID
    created_at: datetime
    processed_at: datetime
    tenant_id: UUID
    project_id: UUID
    project_name: str
    provider: str
    model: str
    original_model: Optional[str] = None
    stream: bool
    status: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_microdollars: int
    actual_cost_microdollars: int
    latency_ms: float
    attempt_count: int
    fallback_used: bool
    router_mode: Optional[str] = None
    router_route: Optional[str] = None
    router_confidence: Optional[float] = None
    router_model_version: Optional[str] = None
    router_fallback: bool = False
    cache_status: Optional[str] = None


class CurrentUserProfile(BaseModel):
    user_id: Optional[UUID] = None
    email: Optional[str] = None
    name: str
    role: str
    tenant_id: UUID
    tenant_name: str
    project_id: Optional[UUID] = None
    projects: List[Dict[str, Any]] = Field(default_factory=list)


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    email: str
    password: str = Field(..., min_length=8, max_length=128)
    tenant_name: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    user: CurrentUserProfile
