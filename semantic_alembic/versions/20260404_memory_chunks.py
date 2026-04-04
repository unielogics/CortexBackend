"""memory_chunks + pgvector

Revision ID: sem_mem_001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "sem_mem_001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.create_table(
        "memory_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("ledger_run_id", sa.String(length=36), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("engagement_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_tag", sa.String(length=64), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_memory_chunks_idempotency"),
    )
    op.create_index("ix_memory_chunks_tenant_id", "memory_chunks", ["tenant_id"])
    op.create_index("ix_memory_chunks_ledger_run_id", "memory_chunks", ["ledger_run_id"])
    op.create_index("ix_memory_chunks_proposal_id", "memory_chunks", ["proposal_id"])
    op.create_index("ix_memory_chunks_source", "memory_chunks", ["source"])


def downgrade() -> None:
    op.drop_table("memory_chunks")
