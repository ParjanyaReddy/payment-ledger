"""Pydantic Schemas for Ledger Reconciliation and Audit Operations."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DiscrepancyDetail(BaseModel):
    """Details of an audited account with balance drift."""

    account_id: uuid.UUID
    currency: str
    actual_balance: str
    expected_balance: str
    drift: str
    reason: str


class ReconciliationResponse(BaseModel):
    """Detailed audit report from a ledger reconciliation run."""

    reconciliation_id: uuid.UUID
    status: str = Field(description="Audit outcome: HEALTHY or DRIFT_DETECTED")
    accounts_audited: int
    transactions_audited: int
    drifts_detected: int
    discrepancies: list[DiscrepancyDetail] = Field(default_factory=list)
    execution_time_ms: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReconciliationStatusResponse(BaseModel):
    """Summary of overall ledger integrity and latest reconciliation run."""

    system_health: str = Field(description="HEALTHY, DRIFT_DETECTED, or NO_RUNS")
    total_runs: int
    last_audited_at: datetime | None = None
    latest_run: ReconciliationResponse | None = None
