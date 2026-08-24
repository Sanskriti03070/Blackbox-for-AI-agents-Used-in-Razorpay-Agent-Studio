"""agent persistence foundation

Revision ID: 20260822_0003
Revises: 20260822_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0003"
down_revision: str | Sequence[str] | None = "20260822_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("agent_name", sa.String(length=128), nullable=False),
        sa.Column("agent_version", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id", ondelete="SET NULL")),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL")),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subscriptions.id", ondelete="SET NULL")),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id", ondelete="SET NULL")),
        sa.Column("user_request", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("selected_action", sa.String(length=64)),
        sa.Column("confidence", sa.Float()),
        sa.Column("outcome", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_summary", sa.Text()),
        sa.Column("metadata", postgresql.JSONB()),
    )
    op.create_index("ix_agent_runs_agent_name", "agent_runs", ["agent_name"])
    op.create_index("ix_agent_runs_merchant_id", "agent_runs", ["merchant_id"])
    op.create_index("ix_agent_runs_customer_id", "agent_runs", ["customer_id"])
    op.create_index("ix_agent_runs_subscription_id", "agent_runs", ["subscription_id"])
    op.create_index("ix_agent_runs_payment_id", "agent_runs", ["payment_id"])
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    op.create_table(
        "agent_trace_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("payload", postgresql.JSONB()),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error_text", sa.Text()),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_trace_run_sequence"),
    )
    op.create_index("ix_agent_trace_events_run_id", "agent_trace_events", ["run_id"])
    op.create_index("ix_agent_trace_events_source", "agent_trace_events", ["source"])
    op.create_index("ix_agent_trace_events_event_type", "agent_trace_events", ["event_type"])
    op.create_index("ix_agent_trace_events_run_id_sequence", "agent_trace_events", ["run_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_agent_trace_events_run_id_sequence", table_name="agent_trace_events")
    op.drop_index("ix_agent_trace_events_event_type", table_name="agent_trace_events")
    op.drop_index("ix_agent_trace_events_source", table_name="agent_trace_events")
    op.drop_index("ix_agent_trace_events_run_id", table_name="agent_trace_events")
    op.drop_table("agent_trace_events")

    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_started_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_payment_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_subscription_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_customer_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_merchant_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_name", table_name="agent_runs")
    op.drop_table("agent_runs")
