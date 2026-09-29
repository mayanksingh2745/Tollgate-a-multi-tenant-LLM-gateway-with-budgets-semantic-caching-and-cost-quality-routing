"""Phase 8 - Semantic Response Cache with pgvector

Revision ID: 0005_phase8_semantic_cache
Revises: 0004_add_user_id_to_api_keys
Create Date: 2026-09-30 01:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0005_phase8_semantic_cache"
down_revision: Union[str, None] = "0004_add_user_id_to_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Enable pgvector extension on PostgreSQL
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Create semantic_cache_entries table
    op.create_table(
        "semantic_cache_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("semantic_representation", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("embedding_model", sa.String(64), nullable=False),
        sa.Column("embedding_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("response_cache_key", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "entry_metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )

    # 3. Create filtering indexes
    op.create_index(
        "idx_semantic_cache_lookup",
        "semantic_cache_entries",
        ["tenant_id", "project_id", "provider", "model", "expires_at"],
    )
    op.create_index(
        "idx_semantic_cache_fingerprint",
        "semantic_cache_entries",
        ["request_fingerprint"],
    )
    op.create_index(
        "idx_semantic_cache_expires_at",
        "semantic_cache_entries",
        ["expires_at"],
    )

    # 4. Create HNSW vector index on PostgreSQL
    if is_postgres:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_cache_embedding "
            "ON semantic_cache_entries USING hnsw (embedding vector_cosine_ops);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS idx_semantic_cache_embedding;")

    op.drop_index("idx_semantic_cache_expires_at", table_name="semantic_cache_entries")
    op.drop_index("idx_semantic_cache_fingerprint", table_name="semantic_cache_entries")
    op.drop_index("idx_semantic_cache_lookup", table_name="semantic_cache_entries")
    op.drop_table("semantic_cache_entries")
