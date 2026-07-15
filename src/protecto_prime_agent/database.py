from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from .logging import log_contextual
    from .models import Base

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - defensive for startup without DB
        log_contextual("database_init_failed", error=str(exc))


async def check_database_health() -> dict[str, Any]:
    from sqlalchemy import text

    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
        await session.commit()
    return {"status": "ok"}
