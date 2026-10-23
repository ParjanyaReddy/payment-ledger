"""Health and Readiness Monitoring Endpoints.

Provides /health for container liveness and /ready for database dependency readiness.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import check_db_health

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    """Liveness probe to confirm the application process is running."""
    return {
        "status": "healthy",
        "app_env": settings.app_env,
        "service": "payment-ledger",
    }


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe verifying connectivity to PostgreSQL backend."""
    is_db_ready = await check_db_health()
    if is_db_ready:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ready", "database": "connected"},
        )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "not_ready", "database": "disconnected"},
    )
