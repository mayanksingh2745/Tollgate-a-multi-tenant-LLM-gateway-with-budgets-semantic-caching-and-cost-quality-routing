from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    log_level: str = "INFO"

    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000

    # CORS configuration
    cors_allowed_origins: list[str] = Field(
        default=["*"],
        validation_alias=AliasChoices("TOLLGATE_CORS_ALLOWED_ORIGINS", "cors_allowed_origins"),
    )

    # HTTP & Reverse Proxy Security Settings
    docs_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("TOLLGATE_DOCS_ENABLED", "docs_enabled"),
    )
    enable_hsts: bool = Field(
        False,
        validation_alias=AliasChoices("TOLLGATE_ENABLE_HSTS", "enable_hsts"),
    )
    trusted_proxies: list[str] = Field(
        default=["127.0.0.1", "::1"],
        validation_alias=AliasChoices("TOLLGATE_TRUSTED_PROXIES", "trusted_proxies"),
    )

    postgres_user: str = "tollgate"
    postgres_password: str = "tollgate_secret_pass"
    postgres_db: str = "tollgate_db"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    database_url: str = (
        "postgresql+asyncpg://tollgate:tollgate_secret_pass@postgres:5432/tollgate_db"
    )

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_url: str = "redis://redis:6379/0"

    # Reliability & Retry Settings
    max_retries: int = Field(
        3, validation_alias=AliasChoices("TOLLGATE_MAX_RETRIES", "max_retries")
    )
    retry_base_delay: float = Field(
        0.25, validation_alias=AliasChoices("TOLLGATE_RETRY_BASE_DELAY", "retry_base_delay")
    )
    retry_max_delay: float = Field(
        5.0, validation_alias=AliasChoices("TOLLGATE_RETRY_MAX_DELAY", "retry_max_delay")
    )
    retry_jitter: bool = Field(
        True, validation_alias=AliasChoices("TOLLGATE_RETRY_JITTER", "retry_jitter")
    )
    request_timeout_seconds: float = Field(
        60.0,
        validation_alias=AliasChoices(
            "TOLLGATE_REQUEST_TIMEOUT_SECONDS", "request_timeout_seconds"
        ),
    )
    provider_timeout_seconds: float = Field(
        30.0,
        validation_alias=AliasChoices(
            "TOLLGATE_PROVIDER_TIMEOUT_SECONDS", "provider_timeout_seconds"
        ),
    )
    provider_cooldown_seconds: float = Field(
        30.0,
        validation_alias=AliasChoices(
            "TOLLGATE_PROVIDER_COOLDOWN_SECONDS", "provider_cooldown_seconds"
        ),
    )

    # Phase 12 Circuit Breaker Settings
    circuit_breaker_enabled: bool = Field(
        True,
        validation_alias=AliasChoices(
            "TOLLGATE_CIRCUIT_BREAKER_ENABLED", "circuit_breaker_enabled"
        ),
    )
    circuit_failure_threshold: int = Field(
        5,
        validation_alias=AliasChoices(
            "TOLLGATE_CIRCUIT_FAILURE_THRESHOLD", "circuit_failure_threshold"
        ),
    )
    circuit_failure_window_seconds: float = Field(
        30.0,
        validation_alias=AliasChoices(
            "TOLLGATE_CIRCUIT_FAILURE_WINDOW_SECONDS", "circuit_failure_window_seconds"
        ),
    )
    circuit_open_duration_seconds: float = Field(
        30.0,
        validation_alias=AliasChoices(
            "TOLLGATE_CIRCUIT_OPEN_DURATION_SECONDS", "circuit_open_duration_seconds"
        ),
    )
    circuit_half_open_max_calls: int = Field(
        1,
        validation_alias=AliasChoices(
            "TOLLGATE_CIRCUIT_HALF_OPEN_MAX_CALLS", "circuit_half_open_max_calls"
        ),
    )
    circuit_rate_limit_threshold: int = Field(
        10,
        validation_alias=AliasChoices(
            "TOLLGATE_CIRCUIT_RATE_LIMIT_THRESHOLD", "circuit_rate_limit_threshold"
        ),
    )

    # Distributed Rate Limiting Settings
    rate_limit_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("TOLLGATE_RATE_LIMIT_ENABLED", "rate_limit_enabled"),
    )
    rate_limit_requests_per_second: float = Field(
        10.0,
        validation_alias=AliasChoices(
            "TOLLGATE_RATE_LIMIT_REQUESTS_PER_SECOND",
            "rate_limit_requests_per_second",
        ),
    )
    rate_limit_burst: int = Field(
        20,
        validation_alias=AliasChoices("TOLLGATE_RATE_LIMIT_BURST", "rate_limit_burst"),
    )
    rate_limit_redis_prefix: str = Field(
        "tg:ratelimit",
        validation_alias=AliasChoices(
            "TOLLGATE_RATE_LIMIT_REDIS_PREFIX", "rate_limit_redis_prefix"
        ),
    )
    rate_limit_redis_timeout_seconds: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "TOLLGATE_RATE_LIMIT_REDIS_TIMEOUT_SECONDS",
            "rate_limit_redis_timeout_seconds",
        ),
    )
    rate_limit_redis_failure_mode: str = Field(
        "closed",
        validation_alias=AliasChoices(
            "TOLLGATE_RATE_LIMIT_REDIS_FAILURE_MODE",
            "rate_limit_redis_failure_mode",
        ),
    )

    # Budget Reservation & Settlement Settings
    budget_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("TOLLGATE_BUDGET_ENABLED", "budget_enabled"),
    )
    budget_reservation_ttl_seconds: int = Field(
        120,
        validation_alias=AliasChoices(
            "TOLLGATE_BUDGET_RESERVATION_TTL_SECONDS",
            "budget_reservation_ttl_seconds",
        ),
    )
    budget_default_max_output_tokens: int = Field(
        4096,
        validation_alias=AliasChoices(
            "TOLLGATE_DEFAULT_MAX_OUTPUT_TOKENS",
            "budget_default_max_output_tokens",
        ),
    )
    budget_redis_timeout_seconds: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "TOLLGATE_BUDGET_REDIS_TIMEOUT_SECONDS",
            "budget_redis_timeout_seconds",
        ),
    )

    # Phase 6 Usage Pipeline & Cost Accounting Settings
    usage_stream: str = Field(
        "tg:usage:events",
        validation_alias=AliasChoices("TOLLGATE_USAGE_STREAM", "usage_stream"),
    )
    usage_consumer_group: str = Field(
        "tg-usage-workers",
        validation_alias=AliasChoices("TOLLGATE_USAGE_CONSUMER_GROUP", "usage_consumer_group"),
    )
    usage_consumer_name: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("TOLLGATE_USAGE_CONSUMER_NAME", "usage_consumer_name"),
    )
    usage_dead_letter_stream: str = Field(
        "tg:usage:dead-letter",
        validation_alias=AliasChoices(
            "TOLLGATE_USAGE_DEAD_LETTER_STREAM", "usage_dead_letter_stream"
        ),
    )
    usage_batch_size: int = Field(
        50,
        validation_alias=AliasChoices("TOLLGATE_USAGE_BATCH_SIZE", "usage_batch_size"),
    )
    usage_max_retries: int = Field(
        3,
        validation_alias=AliasChoices("TOLLGATE_USAGE_MAX_RETRIES", "usage_max_retries"),
    )
    usage_retry_base_delay: float = Field(
        0.25,
        validation_alias=AliasChoices("TOLLGATE_USAGE_RETRY_BASE_DELAY", "usage_retry_base_delay"),
    )
    usage_retry_max_delay: float = Field(
        5.0,
        validation_alias=AliasChoices("TOLLGATE_USAGE_RETRY_MAX_DELAY", "usage_retry_max_delay"),
    )
    usage_claim_idle_seconds: int = Field(
        60,
        validation_alias=AliasChoices(
            "TOLLGATE_USAGE_CLAIM_IDLE_SECONDS", "usage_claim_idle_seconds"
        ),
    )
    usage_block_ms: int = Field(
        2000,
        validation_alias=AliasChoices("TOLLGATE_USAGE_BLOCK_MS", "usage_block_ms"),
    )

    # Phase 7 Exact Response Cache Settings
    cache_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("TOLLGATE_CACHE_ENABLED", "cache_enabled"),
    )
    cache_ttl_seconds: int = Field(
        300,
        validation_alias=AliasChoices("TOLLGATE_CACHE_TTL_SECONDS", "cache_ttl_seconds"),
    )
    cache_max_response_bytes: int = Field(
        524288,
        validation_alias=AliasChoices(
            "TOLLGATE_CACHE_MAX_RESPONSE_BYTES", "cache_max_response_bytes"
        ),
    )
    cache_redis_prefix: str = Field(
        "tg:cache",
        validation_alias=AliasChoices("TOLLGATE_CACHE_REDIS_PREFIX", "cache_redis_prefix"),
    )
    cache_header_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("TOLLGATE_CACHE_HEADER_ENABLED", "cache_header_enabled"),
    )

    # Phase 8 Semantic Response Cache Settings
    semantic_cache_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("TOLLGATE_SEMANTIC_CACHE_ENABLED", "semantic_cache_enabled"),
    )
    semantic_cache_shadow_mode: bool = Field(
        False,
        validation_alias=AliasChoices(
            "TOLLGATE_SEMANTIC_CACHE_SHADOW_MODE", "semantic_cache_shadow_mode"
        ),
    )
    embedding_provider: str = Field(
        "mock",
        validation_alias=AliasChoices("TOLLGATE_EMBEDDING_PROVIDER", "embedding_provider"),
    )
    embedding_model: str = Field(
        "text-embedding-3-small",
        validation_alias=AliasChoices("TOLLGATE_EMBEDDING_MODEL", "embedding_model"),
    )
    embedding_dimension: int = Field(
        1536,
        validation_alias=AliasChoices("TOLLGATE_EMBEDDING_DIMENSION", "embedding_dimension"),
    )
    embedding_timeout_seconds: float = Field(
        3.0,
        validation_alias=AliasChoices(
            "TOLLGATE_EMBEDDING_TIMEOUT_SECONDS", "embedding_timeout_seconds"
        ),
    )
    embedding_api_key: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("TOLLGATE_EMBEDDING_API_KEY", "embedding_api_key"),
    )
    embedding_api_base: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("TOLLGATE_EMBEDDING_API_BASE", "embedding_api_base"),
    )
    semantic_cache_threshold: float = Field(
        0.85,
        validation_alias=AliasChoices(
            "TOLLGATE_SEMANTIC_CACHE_THRESHOLD", "semantic_cache_threshold"
        ),
    )
    semantic_cache_top_k: int = Field(
        5,
        validation_alias=AliasChoices("TOLLGATE_SEMANTIC_CACHE_TOP_K", "semantic_cache_top_k"),
    )
    semantic_cache_max_candidates: int = Field(
        10,
        validation_alias=AliasChoices(
            "TOLLGATE_SEMANTIC_CACHE_MAX_CANDIDATES", "semantic_cache_max_candidates"
        ),
    )
    semantic_cache_ttl_seconds: int = Field(
        3600,
        validation_alias=AliasChoices(
            "TOLLGATE_SEMANTIC_CACHE_TTL_SECONDS", "semantic_cache_ttl_seconds"
        ),
    )
    semantic_cache_lookup_timeout_seconds: float = Field(
        1.0,
        validation_alias=AliasChoices(
            "TOLLGATE_SEMANTIC_CACHE_LOOKUP_TIMEOUT_SECONDS",
            "semantic_cache_lookup_timeout_seconds",
        ),
    )

    # Phase 9 Learned Model Router Settings
    router_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("TOLLGATE_ROUTER_ENABLED", "router_enabled"),
    )
    router_mode: str = Field(
        "disabled",
        validation_alias=AliasChoices("TOLLGATE_ROUTER_MODE", "router_mode"),
    )
    router_shadow_mode: bool = Field(
        False,
        validation_alias=AliasChoices("TOLLGATE_ROUTER_SHADOW_MODE", "router_shadow_mode"),
    )
    router_cheap_model: str = Field(
        "mock-fast",
        validation_alias=AliasChoices("TOLLGATE_ROUTER_CHEAP_MODEL", "router_cheap_model"),
    )
    router_strong_model: str = Field(
        "mock-model",
        validation_alias=AliasChoices("TOLLGATE_ROUTER_STRONG_MODEL", "router_strong_model"),
    )
    router_quality_threshold: float = Field(
        0.7,
        validation_alias=AliasChoices(
            "TOLLGATE_ROUTER_QUALITY_THRESHOLD", "router_quality_threshold"
        ),
    )
    router_fallback_model: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("TOLLGATE_ROUTER_FALLBACK_MODEL", "router_fallback_model"),
    )
    router_model_version: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("TOLLGATE_ROUTER_MODEL_VERSION", "router_model_version"),
    )
    router_artifact_path: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("TOLLGATE_ROUTER_ARTIFACT_PATH", "router_artifact_path"),
    )
    router_max_quality_degradation: float = Field(
        0.05,
        validation_alias=AliasChoices(
            "TOLLGATE_ROUTER_MAX_QUALITY_DEGRADATION",
            "router_max_quality_degradation",
        ),
    )

    # Phase 11A OpenTelemetry & Distributed Tracing Settings
    otel_enabled: bool = Field(
        False,
        validation_alias=AliasChoices("TOLLGATE_OTEL_ENABLED", "otel_enabled"),
    )
    otel_endpoint: str = Field(
        "http://localhost:4318",
        validation_alias=AliasChoices("TOLLGATE_OTEL_ENDPOINT", "otel_endpoint"),
    )
    otel_service_name: str = Field(
        "tollgate-api",
        validation_alias=AliasChoices("TOLLGATE_OTEL_SERVICE_NAME", "otel_service_name"),
    )
    otel_trace_sample_rate: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices("TOLLGATE_OTEL_TRACE_SAMPLE_RATE", "otel_trace_sample_rate"),
    )
    otel_export_timeout_seconds: float = Field(
        2.0,
        validation_alias=AliasChoices(
            "TOLLGATE_OTEL_EXPORT_TIMEOUT_SECONDS", "otel_export_timeout_seconds"
        ),
    )

    # Phase 11B Prometheus Metrics Settings
    metrics_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("TOLLGATE_METRICS_ENABLED", "metrics_enabled"),
    )
    metrics_auth_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("TOLLGATE_METRICS_AUTH_ENABLED", "metrics_auth_enabled"),
    )
    metrics_token: str = Field(
        "tollgate-metrics-secret-token",
        validation_alias=AliasChoices("TOLLGATE_METRICS_TOKEN", "metrics_token"),
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()


def get_settings() -> Settings:
    return settings
