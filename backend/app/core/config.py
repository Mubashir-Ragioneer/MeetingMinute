# app/core/config.py
from functools import lru_cache
from typing import List

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ---- App ----
    APP_NAME: str = "Minute-Mate API"
    DEBUG: bool = False
    ENV: str = "local"  # local | docker | prod

    # ---- Mongo ----
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "minutemate"

    # ---- CORS ----
    CORS_ORIGINS: List[AnyHttpUrl] = []
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["*"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]

    # ---- Secrets / APIs (add what you need) ----
    OPENAI_API_KEY: str | None = None

    # Pydantic Settings config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def split_origins(cls, v):
        """
        Allow both a comma-separated string and a proper JSON list.
        CORS_ORIGINS=http://localhost:3000,https://example.com
        """
        if isinstance(v, str) and v:
            return [o.strip() for o in v.split(",")]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Singleton-like access everywhere:
settings = get_settings()
