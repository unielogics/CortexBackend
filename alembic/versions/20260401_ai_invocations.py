"""create ai_invocations

Revision ID: 20260401_ai_invocations
Revises:
Create Date: 2026-04-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260401_ai_invocations"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("engagement_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=96), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=True),
        sa.Column("prompt_preview", sa.Text(), nullable=True),
        sa.Column("response_preview", sa.Text(), nullable=True),
        sa.Column("extra_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_invocations_capability"), "ai_invocations", ["capability"], unique=False)
    op.create_index(op.f("ix_ai_invocations_created_at"), "ai_invocations", ["created_at"], unique=False)
    op.create_index(op.f("ix_ai_invocations_engagement_id"), "ai_invocations", ["engagement_id"], unique=False)
    op.create_index(op.f("ix_ai_invocations_proposal_id"), "ai_invocations", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_ai_invocations_run_id"), "ai_invocations", ["run_id"], unique=False)
    op.create_index(op.f("ix_ai_invocations_tenant_id"), "ai_invocations", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_ai_invocations_correlation_id"), "ai_invocations", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_ai_invocations_source"), "ai_invocations", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_invocations_source"), table_name="ai_invocations")
    op.drop_index(op.f("ix_ai_invocations_correlation_id"), table_name="ai_invocations")
    op.drop_index(op.f("ix_ai_invocations_tenant_id"), table_name="ai_invocations")
    op.drop_index(op.f("ix_ai_invocations_run_id"), table_name="ai_invocations")
    op.drop_index(op.f("ix_ai_invocations_proposal_id"), table_name="ai_invocations")
    op.drop_index(op.f("ix_ai_invocations_engagement_id"), table_name="ai_invocations")
    op.drop_index(op.f("ix_ai_invocations_created_at"), table_name="ai_invocations")
    op.drop_index(op.f("ix_ai_invocations_capability"), table_name="ai_invocations")
    op.drop_table("ai_invocations")
