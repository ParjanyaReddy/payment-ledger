"""add_card_authorizations_and_account_holds

Revision ID: c56b02a78129
Revises: f0553f9746bb
Create Date: 2026-10-23 18:32:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c56b02a78129"
down_revision: str | Sequence[str] | None = "f0553f9746bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: holds column and constraints on accounts, card_authorizations table."""
    # 1. Add holds column to accounts
    op.add_column(
        "accounts",
        sa.Column(
            "holds",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default="0.00",
        ),
    )
    op.create_check_constraint(
        "check_account_holds_non_negative",
        "accounts",
        "holds >= 0",
    )
    op.create_check_constraint(
        "check_account_balance_covers_holds",
        "accounts",
        "balance >= holds",
    )

    # 2. Create card_authorizations table
    op.create_table(
        "card_authorizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("captured_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "refunded_amount",
            sa.Numeric(precision=18, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="AUTHORIZED",
            nullable=False,
        ),
        sa.Column("memo", sa.String(length=255), nullable=True),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("refund_transaction_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_card_authorizations_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["accounts.id"],
            name="fk_card_authorizations_merchant_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_card_authorizations_transaction_id_transactions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["refund_transaction_id"],
            ["transactions.id"],
            name="fk_card_authorizations_refund_transaction_id_transactions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount > 0", name="check_card_auth_amount_positive"),
        sa.CheckConstraint(
            "refunded_amount >= 0",
            name="check_card_auth_refunded_amount_non_negative",
        ),
        sa.CheckConstraint(
            "status IN ('AUTHORIZED', 'CAPTURED', 'VOIDED', 'REFUNDED')",
            name="check_card_auth_status_valid",
        ),
    )
    op.create_index(
        "ix_card_authorizations_account_id",
        "card_authorizations",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_card_authorizations_status",
        "card_authorizations",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_card_authorizations_status", table_name="card_authorizations")
    op.drop_index("ix_card_authorizations_account_id", table_name="card_authorizations")
    op.drop_table("card_authorizations")
    op.drop_constraint("check_account_balance_covers_holds", "accounts", type_="check")
    op.drop_constraint("check_account_holds_non_negative", "accounts", type_="check")
    op.drop_column("accounts", "holds")
