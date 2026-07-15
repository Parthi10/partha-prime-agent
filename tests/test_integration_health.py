from __future__ import annotations

import os

import pytest

from protecto_prime_agent.database import check_database_health
from protecto_prime_agent.redis_client import check_redis_health


def _should_skip_integration_tests() -> bool:
    return os.getenv("SKIP_INTEGRATION_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.mark.asyncio
async def test_database_health() -> None:
    try:
        result = await check_database_health()
    except Exception as exc:  # pragma: no cover - depends on local DB availability
        if _should_skip_integration_tests():
            pytest.skip(f"PostgreSQL unavailable: {exc}")
        raise
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_redis_health() -> None:
    try:
        result = await check_redis_health()
    except Exception as exc:  # pragma: no cover - depends on local Redis availability
        if _should_skip_integration_tests():
            pytest.skip(f"Redis unavailable: {exc}")
        raise
    assert result["status"] == "ok"
