"""Phase 10 - Dashboard Analytics & Request Metadata

Revision ID: 0006_phase10_dashboard_analytics
Revises: 0005_phase8_semantic_cache
Create Date: 2026-09-30 02:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase10_dashboard_analytics"
down_revision: Union[str, None] = "0005_phase8_semantic_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add analytics and routing columns to usage_events
    op.add_column("usage_events", sa.Column("cache_status", sa.String(length=32), nullable=True))
    op.add_column("usage_events", sa.Column("router_mode", sa.String(length=32), nullable=True))
    op.add_column("usage_events", sa.Column("router_route", sa.String(length=32), nullable=True))
    op.add_column("usage_events", sa.Column("router_confidence", sa.Float(), nullable=True))
    op.add_column(
        "usage_events", sa.Column("router_model_version", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "usage_events",
        sa.Column("router_fallback", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    op.add_column("usage_events", sa.Column("original_model", sa.String(length=128), nullable=True))

    # 2. Add indexing for optimized dashboard queries
    op.create_index(
        "idx_usage_events_tenant_status", "usage_events", ["tenant_id", "status", "created_at"]
    )
    op.create_index(
        "idx_usage_events_tenant_model", "usage_events", ["tenant_id", "model", "created_at"]
    )
    op.create_index(
        "idx_usage_events_tenant_provider", "usage_events", ["tenant_id", "provider", "created_at"]
    )
    op.create_index(
        "idx_usage_events_tenant_route", "usage_events", ["tenant_id", "router_route", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_usage_events_tenant_route", table_name="usage_events")
    op.drop_index("idx_usage_events_tenant_provider", table_name="usage_events")
    op.drop_index("idx_usage_events_tenant_model", table_name="usage_events")
    op.drop_index("idx_usage_events_tenant_status", table_name="usage_events")

    op.drop_column("usage_events", "original_model")
    op.drop_column("usage_events", "router_fallback")
    op.drop_column("usage_events", "router_model_version")
    op.drop_column("usage_events", "router_confidence")
    op.drop_column("usage_events", "router_route")
    op.drop_column("usage_events", "router_mode")
    op.drop_column("usage_events", "cache_status")
