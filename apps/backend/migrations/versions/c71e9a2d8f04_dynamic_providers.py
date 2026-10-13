"""Dynamic provider endpoints and cached model catalog.

Revision ID: c71e9a2d8f04
Revises: 9d6f4a8c2e11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c71e9a2d8f04"
down_revision: str | None = "9d6f4a8c2e11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        with op.get_context().autocommit_block():
            op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("provider_connections") as batch:
        batch.drop_constraint("ck_provider_connections_provider", type_="check")
        batch.add_column(sa.Column("base_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("models_json", sa.Text(), nullable=False, server_default="[]"))
    with op.batch_alter_table("provider_connections") as batch:
        batch.alter_column("models_json", server_default=None)
    op.add_column("agent_tasks", sa.Column("review_notes", sa.Text(), nullable=True))
    op.add_column(
        "project_plans",
        sa.Column("planning_mode", sa.String(30), nullable=False, server_default="template"),
    )
    with op.batch_alter_table("project_plans") as batch:
        batch.alter_column("planning_mode", server_default=None)
    if sqlite:
        with op.get_context().autocommit_block():
            op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")
            if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("Database contains invalid workflow references")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM provider_connections "
                "WHERE provider NOT IN ('openai', 'anthropic', 'gemini', 'openrouter')"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Rollback requires exporting and removing new provider connections first"
        )
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        with op.get_context().autocommit_block():
            op.get_bind().exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("provider_connections") as batch:
        batch.drop_column("models_json")
        batch.drop_column("base_url")
        batch.create_check_constraint(
            "ck_provider_connections_provider",
            "provider IN ('openai', 'anthropic', 'gemini', 'openrouter')",
        )
    op.drop_column("agent_tasks", "review_notes")
    with op.batch_alter_table("project_plans") as batch:
        batch.drop_column("planning_mode")
    if sqlite:
        with op.get_context().autocommit_block():
            op.get_bind().exec_driver_sql("PRAGMA foreign_keys=ON")
