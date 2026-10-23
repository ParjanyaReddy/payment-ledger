"""add_ledger_immutability_trigger_and_reconciliation_runs

Revision ID: f0553f9746bb
Revises: 62c0bae9fb42
Create Date: 2026-10-23 17:59:20.872358

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f0553f9746bb"
down_revision: str | Sequence[str] | None = "62c0bae9fb42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: append-only trigger, initial_balance, reconciliation_runs table."""
    # 1. Add initial_balance column to accounts
    op.add_column(
        "accounts",
        sa.Column(
            "initial_balance",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default="0.00",
        ),
    )
    op.execute(
        "UPDATE accounts SET initial_balance = balance WHERE initial_balance = 0.00 AND balance != 0.00;"
    )

    # 2. Create PostgreSQL function and trigger preventing UPDATE and DELETE on ledger_entries
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_ledger_entry_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'ledger_entries is append-only: UPDATE and DELETE operations are strictly prohibited';
        END;
        $$ LANGUAGE plpgsql;
        """)

    op.execute("""
        CREATE TRIGGER trg_prevent_ledger_entry_mutation
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW
        EXECUTE FUNCTION prevent_ledger_entry_mutation();
        """)

    # 3. Create reconciliation_runs table
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("accounts_audited", sa.Integer(), nullable=False),
        sa.Column("transactions_audited", sa.Integer(), nullable=False),
        sa.Column("drifts_detected", sa.Integer(), nullable=False),
        sa.Column(
            "discrepancies",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("execution_time_ms", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("reconciliation_runs")
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_ledger_entry_mutation ON ledger_entries;")
    op.execute("DROP FUNCTION IF EXISTS prevent_ledger_entry_mutation();")
    op.drop_column("accounts", "initial_balance")
