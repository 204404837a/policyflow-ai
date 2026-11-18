"""users + rbac (submitted_by, patient_name)

Revision ID: b2c3d4e5f6a7
Revises: 1e21a9730ddc
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "1e21a9730ddc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("first_name", sa.String(length=80), nullable=True),
        sa.Column("last_name", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.add_column(
        "cases",
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("cases", sa.Column("patient_name", sa.String(length=120), nullable=True))
    op.create_index(op.f("ix_cases_submitted_by"), "cases", ["submitted_by"], unique=False)
    op.create_foreign_key(
        "cases_submitted_by_fkey", "cases", "users", ["submitted_by"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("cases_submitted_by_fkey", "cases", type_="foreignkey")
    op.drop_index(op.f("ix_cases_submitted_by"), table_name="cases")
    op.drop_column("cases", "patient_name")
    op.drop_column("cases", "submitted_by")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
