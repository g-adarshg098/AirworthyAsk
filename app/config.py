from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    app_name: str = "examate-rag"
    environment: str = "local"  # local | ci | production
    database_url: str | None = None
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_model: str = "gemini-3.5-flash"
    gemini_timeout_seconds: float = Field(default=30, gt=0)
    gemini_retries: int = Field(default=1, ge=0)
    gemini_input_cost_per_million: float | None = Field(default=None, ge=0)
    gemini_output_cost_per_million: float | None = Field(default=None, ge=0)
    gemini_fallback_input_cost_per_million: float | None = Field(default=None, ge=0)
    gemini_fallback_output_cost_per_million: float | None = Field(default=None, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
