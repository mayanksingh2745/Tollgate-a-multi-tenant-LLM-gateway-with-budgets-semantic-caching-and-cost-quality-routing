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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
