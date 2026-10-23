"""Outbox SQLAlchemy ORM Model.

Represents a durable transactional outbox queue for asynchronous AI categorization.
Inserted in the same database transaction as the financial transfer.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Outbox(Base):
    """Outbox model representing durable asynchronous task records."""

    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'DONE', 'FAILED')",
            name="check_outbox_status_valid",
        ),
        Index("ix_outbox_status_created_at", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Outbox id={self.id} transaction_id={self.transaction_id} status={self.status}>"
