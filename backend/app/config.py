from functools import cached_property

from pydantic import AnyHttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: AnyHttpUrl
    supabase_anon_key: str
    supabase_service_role_key: str
    database_url: PostgresDsn
    openai_api_key: str
    allowed_email_domain: str
    allowed_origins: str
    max_upload_bytes: int
    allowed_upload_media_types: str
    openai_chat_model: str
    openai_embedding_model: str
    openai_embedding_dimensions: int

    @field_validator(
        "supabase_anon_key",
        "supabase_service_role_key",
        "openai_api_key",
        "allowed_upload_media_types",
        "openai_chat_model",
        "openai_embedding_model",
    )
    @classmethod
    def require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("allowed_email_domain")
    @classmethod
    def validate_email_domain(cls, value: str) -> str:
        domain = value.strip().lower()
        if domain.startswith("@") or "." not in domain or "@" in domain:
            raise ValueError("must be a domain without '@'")
        return domain

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins:
            raise ValueError("must contain at least one origin")
        for origin in origins:
            AnyHttpUrl(origin)
        return ",".join(origins)

    @field_validator("max_upload_bytes", "openai_embedding_dimensions")
    @classmethod
    def require_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("database_url")
    @classmethod
    def reject_transaction_pooler(cls, value: PostgresDsn) -> PostgresDsn:
        if any(
            host["host"].endswith(".pooler.supabase.com") and host["port"] == 6543
            for host in value.hosts()
        ):
            raise ValueError("must use a direct/session database URL, not the transaction pooler")
        return value

    @cached_property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(self.allowed_origins.split(","))


settings = Settings()
