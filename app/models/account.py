"""Account SQLAlchemy ORM Model.

Represents an account with a cached projection of its balance,
protected by a database-level non-negative check constraint.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Account(Base):
    """Account model representing an entity balance container."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    initial_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (CheckConstraint("balance >= 0", name="check_account_balance_non_negative"),)

    def __init__(self, **kwargs: object) -> None:
        if "balance" in kwargs and "initial_balance" not in kwargs:
            kwargs["initial_balance"] = kwargs["balance"]
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Account id={self.id} currency={self.currency} balance={self.balance}>"
