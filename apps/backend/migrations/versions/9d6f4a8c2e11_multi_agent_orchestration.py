"""multi-agent orchestration

Revision ID: 9d6f4a8c2e11
Revises: 367de70e7ad3
Create Date: 2026-10-12 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d6f4a8c2e11"
down_revision: str | None = "367de70e7ad3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("key_last_four", sa.String(length=4), nullable=False),
        sa.Column("default_model", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=20), nullable=True),
        sa.Column("last_test_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('openai', 'anthropic', 'gemini', 'openrouter')",
            name="ck_provider_connections_provider",
        ),
        sa.CheckConstraint(
            "status IN ('untested', 'active', 'invalid', 'disabled')",
            name="ck_provider_connections_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", "label", name="uq_provider_connections_user_label"
        ),
    )
    op.create_index(op.f("ix_provider_connections_provider"), "provider_connections", ["provider"])
    op.create_index(op.f("ix_provider_connections_status"), "provider_connections", ["status"])
    op.create_index(op.f("ix_provider_connections_user_id"), "provider_connections", ["user_id"])

    op.create_table(
        "project_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'archived')",
            name="ck_project_plans_status",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_plans_project_id"), "project_plans", ["project_id"])
    op.create_index(op.f("ix_project_plans_status"), "project_plans", ["status"])

    op.create_table(
        "project_repositories",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("repo", sa.String(length=100), nullable=False),
        sa.Column("default_branch", sa.String(length=240), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "plan_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'completed')", name="ck_plan_milestones_status"
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["project_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "position", name="uq_plan_milestones_position"),
    )
    op.create_index(op.f("ix_plan_milestones_plan_id"), "plan_milestones", ["plan_id"])

    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("milestone_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_connection_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("assignment_reason", sa.Text(), nullable=False),
        sa.Column("assigned_model", sa.String(length=240), nullable=True),
        sa.Column("acceptance_criteria_json", sa.Text(), nullable=False),
        sa.Column("dependencies_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("pull_request_url", sa.String(length=500), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('orchestrator', 'product_manager', 'researcher', 'frontend', 'backend', 'api', 'tester')",
            name="ck_agent_tasks_role",
        ),
        sa.CheckConstraint(
            "status IN ('backlog', 'scheduled', 'ready', 'running', 'review', 'completed', 'failed', 'cancelled')",
            name="ck_agent_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_connection_id"], ["provider_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["milestone_id"], ["plan_milestones.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["project_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "assigned_connection_id",
        "milestone_id",
        "plan_id",
        "project_id",
        "role",
        "scheduled_for",
        "status",
    ):
        op.create_index(op.f(f"ix_agent_tasks_{column}"), "agent_tasks", [column])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("usage_json", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_agent_runs_status"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["provider_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("connection_id", "status", "task_id"):
        op.create_index(op.f(f"ix_agent_runs_{column}"), "agent_runs", [column])


def downgrade() -> None:
    for column in ("task_id", "status", "connection_id"):
        op.drop_index(op.f(f"ix_agent_runs_{column}"), table_name="agent_runs")
    op.drop_table("agent_runs")
    for column in (
        "status",
        "scheduled_for",
        "role",
        "project_id",
        "plan_id",
        "milestone_id",
        "assigned_connection_id",
    ):
        op.drop_index(op.f(f"ix_agent_tasks_{column}"), table_name="agent_tasks")
    op.drop_table("agent_tasks")
    op.drop_index(op.f("ix_plan_milestones_plan_id"), table_name="plan_milestones")
    op.drop_table("plan_milestones")
    op.drop_index(op.f("ix_project_plans_status"), table_name="project_plans")
    op.drop_index(op.f("ix_project_plans_project_id"), table_name="project_plans")
    op.drop_table("project_plans")
    op.drop_table("project_repositories")
    op.drop_index(op.f("ix_provider_connections_user_id"), table_name="provider_connections")
    op.drop_index(op.f("ix_provider_connections_status"), table_name="provider_connections")
    op.drop_index(op.f("ix_provider_connections_provider"), table_name="provider_connections")
    op.drop_table("provider_connections")
