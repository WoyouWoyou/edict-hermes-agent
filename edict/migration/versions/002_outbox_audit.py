"""add outbox and audit tables

Revision ID: 002_outbox_audit
Revises: 001_initial
Create Date: 2026-05-02 18:35:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_outbox_audit"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("producer", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default="{}"),
        sa.Column("meta", postgresql.JSONB(), server_default="{}"),
        sa.Column("published", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_outbox_events_published", "outbox_events", ["published"])
    op.create_index(
        "ix_outbox_unpublished",
        "outbox_events",
        ["published", "id"],
        postgresql_where=sa.text("published = false"),
    )
    op.create_index("ix_outbox_created_at", "outbox_events", ["created_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("agent_id", sa.String(50), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), server_default=""),
        sa.Column("meta", postgresql.JSONB(), server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_task_id", "audit_logs", ["task_id"])
    op.create_index("ix_audit_agent_id", "audit_logs", ["agent_id"])
    op.create_index("ix_audit_action", "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_index("ix_audit_action", table_name="audit_logs")
    op.drop_index("ix_audit_agent_id", table_name="audit_logs")
    op.drop_index("ix_audit_task_id", table_name="audit_logs")
    op.drop_index("ix_audit_timestamp", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_outbox_created_at", table_name="outbox_events")
    op.drop_index("ix_outbox_unpublished", table_name="outbox_events")
    op.drop_index("ix_outbox_events_published", table_name="outbox_events")
    op.drop_table("outbox_events")
