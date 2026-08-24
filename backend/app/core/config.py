from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_name: str = "Razorpay AI Black Box"
    app_version: str = "0.1.0"
    app_env: str = "development"
    database_url: PostgresDsn = (
        "postgresql+psycopg://razorpay:change-me-for-local-development@localhost:5432/"
        "razorpay_black_box"
    )
    test_database_url: PostgresDsn = (
        "postgresql+psycopg://razorpay:change-me-for-local-development@localhost:5432/"
        "razorpay_black_box_test"
    )
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.2"
    openai_confidence_threshold: float = 0.7


@lru_cache
def get_settings() -> Settings:
    return Settings()
