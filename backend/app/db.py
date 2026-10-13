import os
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_session_factory = None


def _get_engine():
    global _engine, _session_factory
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL is required when SAMPLE_MODE is false.")
        _engine = create_async_engine(url, echo=False, pool_size=10, max_overflow=20)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine, _session_factory


async def get_db() -> AsyncGenerator[Optional[AsyncSession], None]:
    # Yield None in SAMPLE_MODE so route handlers can guard without attempting a DB connection.
    if os.environ.get("SAMPLE_MODE", "").lower() in ("true", "1"):
        yield None
        return
    _, factory = _get_engine()
    async with factory() as session:
        yield session
