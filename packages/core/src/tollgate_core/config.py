from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    log_level: str = "INFO"

    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
