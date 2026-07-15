from __future__ import annotations

from typing import Any

import redis.asyncio as redis_async

from .config import get_settings

settings = get_settings()


async def check_redis_health() -> dict[str, Any]:
    client = redis_async.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
        return {"status": "ok"}
    finally:
        await client.aclose()
