"""Reconciliation API Endpoints.

Provides HTTP routes for triggering ledger balance audits and querying
system-wide financial integrity status.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.reconciliation import (
    ReconciliationResponse,
    ReconciliationStatusResponse,
)
from app.services.reconciliation import (
    get_reconciliation_status,
    run_reconciliation,
)

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.post(
    "/run",
    response_model=ReconciliationResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger an on-demand ledger reconciliation audit",
)
async def trigger_reconciliation(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReconciliationResponse:
    """Execute a complete audit of all accounts, transactions, and ledger entries."""
    return await run_reconciliation(db=db)


@router.get(
    "/status",
    response_model=ReconciliationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve latest reconciliation audit status and system health",
)
async def fetch_reconciliation_status(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReconciliationStatusResponse:
    """Fetch the latest audit result, total run count, and current health."""
    return await get_reconciliation_status(db=db)
