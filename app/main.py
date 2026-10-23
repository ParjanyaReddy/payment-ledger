"""FastAPI Main Application Entrypoint.

Initializes FastAPI, configures middleware, registers route modules,
and handles application lifecycle events.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_accounts import router as accounts_router
from app.api.routes_health import router as health_router
from app.api.routes_reconciliation import router as reconciliation_router
from app.api.routes_transfers import router as transfers_router
from app.config import get_settings
from app.db import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager for startup and graceful shutdown."""
    # Startup: ensure settings are loaded
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

# Wire routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")
app.include_router(transfers_router, prefix="/api/v1")
app.include_router(reconciliation_router, prefix="/api/v1")


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Root endpoint returning service identity and documentation link."""
    return {
        "service": "Payment Ledger & Real-Time Auditor API",
        "docs": "/docs",
        "health": "/api/v1/health",
        "ready": "/api/v1/ready",
    }
