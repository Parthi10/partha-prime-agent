from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "testing", "production"] = Field(default="development")
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    database_host: str = Field(default="localhost")
    database_port: int = Field(default=5432)
    database_name: str = Field(default="protecto_prime_agent")
    database_user: str = Field(default="protecto")
    database_password: str = Field(default="protecto")

    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_password: str | None = Field(default=None)
    bitbucket_webhook_secret: str | None = Field(default=None)
    github_webhook_secret: str | None = Field(default=None)
    workspace_root: str = Field(default="/tmp/protecto-workspaces")
    git_clone_timeout_seconds: int = Field(default=300)
    git_fetch_timeout_seconds: int = Field(default=300)
    max_workspace_size_mb: int = Field(default=1024)
    workspace_retention_hours: int = Field(default=24)
    git_network_max_retries: int = Field(default=3)
    git_network_retry_backoff_seconds: float = Field(default=0.5)

    @computed_field  # type: ignore[prop-defined]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.database_user}:{self.database_password}@"
            f"{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @computed_field  # type: ignore[prop-defined]
    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
