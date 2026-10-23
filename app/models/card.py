"""CardAuthorization SQLAlchemy ORM Model.

Represents a payment card lifecycle authorization (hold), capture, void, and refund.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CardAuthorization(Base):
    """Card authorization model representing card lifecycle holds and settlements."""

    __tablename__ = "card_authorizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )
    captured_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    refunded_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="AUTHORIZED",
    )
    memo: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    refund_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="check_card_auth_amount_positive"),
        CheckConstraint(
            "refunded_amount >= 0", name="check_card_auth_refunded_amount_non_negative"
        ),
        CheckConstraint(
            "status IN ('AUTHORIZED', 'CAPTURED', 'VOIDED', 'REFUNDED')",
            name="check_card_auth_status_valid",
        ),
        Index("ix_card_authorizations_account_id", "account_id"),
        Index("ix_card_authorizations_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<CardAuthorization id={self.id} account_id={self.account_id} "
            f"amount={self.amount} status={self.status}>"
        )
