"""Phase 5 budget columns migration

Revision ID: 0002_phase5_budgets
Revises: 0001_phase1_identity
Create Date: 2026-09-30 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase5_budgets"
down_revision: Union[str, None] = "0001_phase1_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants", sa.Column("monthly_budget_microdollars", sa.BigInteger(), nullable=True)
    )
    op.add_column("tenants", sa.Column("daily_budget_microdollars", sa.BigInteger(), nullable=True))
    op.add_column(
        "projects", sa.Column("monthly_budget_microdollars", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("daily_budget_microdollars", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("projects", "daily_budget_microdollars")
    op.drop_column("projects", "monthly_budget_microdollars")
    op.drop_column("tenants", "daily_budget_microdollars")
    op.drop_column("tenants", "monthly_budget_microdollars")
