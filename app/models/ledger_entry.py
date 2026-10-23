"""LedgerEntry SQLAlchemy ORM Model.

Represents an immutable, append-only double-entry bookkeeping record.
Every transfer transaction must produce exactly two entries: one DEBIT and one CREDIT.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LedgerEntry(Base):
    """LedgerEntry model recording atomic debit/credit movements."""

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_ledger_entry_amount_positive"),
        CheckConstraint(
            "direction IN ('DEBIT', 'CREDIT')",
            name="check_ledger_entry_direction_valid",
        ),
        Index("ix_ledger_entries_account_id", "account_id"),
        Index("ix_ledger_entries_transaction_id", "transaction_id"),
    )

    def __repr__(self) -> str:
        return f"<LedgerEntry id={self.id} account_id={self.account_id} direction={self.direction} amount={self.amount}>"
