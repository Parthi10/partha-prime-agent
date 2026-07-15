from __future__ import annotations

from protecto_prime_agent.config import Settings, get_settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.app_env == "development"
    assert settings.api_host == "0.0.0.0"
    assert settings.database_name == "protecto_prime_agent"


def test_get_settings_is_cached() -> None:
    first = get_settings()
    second = get_settings()
    assert first is second
