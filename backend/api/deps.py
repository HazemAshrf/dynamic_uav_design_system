"""API dependencies."""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db as get_database_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async for session in get_database_session():
        yield session