from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    base_url: str = "http://localhost:8000"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/url_shortener"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 86400  # 24 hours
    short_code_length: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
