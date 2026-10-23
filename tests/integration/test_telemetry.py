"""Integration Tests for Telemetry, Request ID Tracing, and Prometheus Metrics."""

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_id_generated_when_missing(async_client: AsyncClient) -> None:
    """Verify that requests without X-Request-ID receive a generated UUID in the response."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    req_id = response.headers.get("X-Request-ID")
    assert req_id is not None
    # Validate it is a valid UUID
    parsed = uuid.UUID(req_id)
    assert parsed.version == 4


@pytest.mark.asyncio
async def test_request_id_preserved_when_provided(async_client: AsyncClient) -> None:
    """Verify that incoming X-Request-ID is preserved and reflected in the response header."""
    custom_id = "test-req-id-12345"
    response = await async_client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint(async_client: AsyncClient) -> None:
    """Verify that /metrics exposes Prometheus formatted metrics."""
    # Generate some traffic first
    await async_client.get("/api/v1/health")
    await async_client.get("/")

    # Scrape metrics
    response = await async_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    content = response.text
    assert "http_requests_total" in content
    assert "http_request_duration_seconds" in content
