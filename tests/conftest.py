"""Pytest Configuration and Test Fixtures.

Configures test database engine and sessionmaker with connection pooling,
and overrides FastAPI get_db dependency for integration and concurrency tests.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db import get_db
from app.main import app

settings = get_settings()

# Test engine configured with a bounded connection pool to stay well within
# PostgreSQL's max_connections limit during high-concurrency stress tests.
test_engine: AsyncEngine = create_async_engine(
    settings.test_database_url,
    pool_size=25,
    max_overflow=25,
    pool_timeout=30.0,
    pool_pre_ping=True,
    echo=False,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated database session connected to the test database."""
    async with TestingSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Yield an HTTP test client with get_db overridden to use the test database."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
