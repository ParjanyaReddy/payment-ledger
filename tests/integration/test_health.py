"""Integration Tests for Health and Root Endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient) -> None:
    """Verify that root endpoint returns service identity and status 200."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert data["health"] == "/api/v1/health"
    assert data["ready"] == "/api/v1/ready"


@pytest.mark.asyncio
async def test_health_endpoint(async_client: AsyncClient) -> None:
    """Verify liveness probe returns status 200 and healthy payload."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "payment-ledger"


@pytest.mark.asyncio
async def test_readiness_endpoint(async_client: AsyncClient) -> None:
    """Verify readiness probe checks PostgreSQL and returns status 200."""
    response = await async_client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
