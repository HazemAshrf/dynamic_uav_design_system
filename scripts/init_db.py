"""Initialize database with tables."""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from backend.core.config import settings
from backend.core.database import Base
from backend.models import *  # Import all models


async def init_db():
    """Create all database tables."""
    
    engine = create_async_engine(settings.database_url)
    
    async with engine.begin() as conn:
        # Drop all tables (for development)
        await conn.run_sync(Base.metadata.drop_all)
        
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    
    await engine.dispose()
    print("Database initialized successfully!")


if __name__ == "__main__":
    asyncio.run(init_db())