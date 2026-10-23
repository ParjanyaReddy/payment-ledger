"""ReconciliationRun SQLAlchemy ORM Model.

Tracks historical ledger balance reconciliation audits and drift detection reports.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReconciliationRun(Base):
    """Stores full audit logs of ledger integrity reconciliation checks."""

    __tablename__ = "reconciliation_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # "HEALTHY" or "DRIFT_DETECTED"
    accounts_audited: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    transactions_audited: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    drifts_detected: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    discrepancies: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    execution_time_ms: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ReconciliationRun id={self.id} status={self.status} "
            f"drifts={self.drifts_detected} accounts={self.accounts_audited}>"
        )
