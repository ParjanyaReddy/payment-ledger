"""FastAPI Main Application Entrypoint.

Initializes FastAPI, configures middleware, registers route modules,
and handles application lifecycle events.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_accounts import router as accounts_router
from app.api.routes_cards import router as cards_router
from app.api.routes_health import router as health_router
from app.api.routes_reconciliation import router as reconciliation_router
from app.api.routes_transfers import router as transfers_router
from app.config import get_settings
from app.db import engine
from app.telemetry import TelemetryMiddleware, metrics_endpoint, setup_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager for startup and graceful shutdown."""
    # Startup: configure structured JSON logging and ensure settings are loaded
    setup_logging()
    _ = settings
    yield
    # Shutdown: gracefully close database connection pool
    await engine.dispose()


app = FastAPI(
    title="Payment Ledger & Real-Time Auditor API",
    description=(
        "Double-entry payment ledger API with provable concurrency guarantees, "
        "race-safe idempotency, append-only integrity, and asynchronous AI categorization."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Enable CORS for local development and dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enable Telemetry & Request ID tracing middleware
app.add_middleware(TelemetryMiddleware)

# Mount frontend static directory
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Wire routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")
app.include_router(transfers_router, prefix="/api/v1")
app.include_router(cards_router, prefix="/api/v1")
app.include_router(reconciliation_router, prefix="/api/v1")


@app.get("/metrics", tags=["Observability"])
async def get_metrics() -> Response:
    """Expose Prometheus telemetry scrape endpoint."""
    return await metrics_endpoint()


@app.get("/dashboard", include_in_schema=False)
async def dashboard_view() -> FileResponse:
    """Serve real-time web auditor dashboard."""
    return FileResponse("app/static/index.html")


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Root endpoint returning service identity and documentation link."""
    return {
        "service": "Payment Ledger & Real-Time Auditor API",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "metrics": "/metrics",
        "health": "/api/v1/health",
        "ready": "/api/v1/ready",
    }
