"""plans and daily usage

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("plan", sa.String(length=16), nullable=False, server_default="free")
        )
        batch.add_column(sa.Column("daily_message_limit", sa.Integer(), nullable=True))
    op.create_table(
        "daily_usage",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("messages", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "day"),
    )


def downgrade() -> None:
    op.drop_table("daily_usage")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("daily_message_limit")
        batch.drop_column("plan")
