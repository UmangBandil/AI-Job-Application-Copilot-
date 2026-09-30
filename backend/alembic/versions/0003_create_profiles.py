"""create profiles table

Revision ID: 0003_create_profiles
Revises: 0002_pgvector_embedding
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_create_profiles"
down_revision = "0002_pgvector_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("github_url", sa.String(500), nullable=True),
        sa.Column("portfolio_url", sa.String(500), nullable=True),
        sa.Column("education", postgresql.JSONB(), nullable=True),
        sa.Column("experience", postgresql.JSONB(), nullable=True),
        sa.Column("skills", postgresql.JSONB(), nullable=True),
        sa.Column("projects", postgresql.JSONB(), nullable=True),
        sa.Column("work_authorization", postgresql.JSONB(), nullable=True),
        sa.Column("notice_period", sa.String(100), nullable=True),
        sa.Column("salary_expectation", sa.String(100), nullable=True),
        sa.Column("willing_to_relocate", sa.Boolean(), nullable=True),
        sa.Column("preferred_locations", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_profiles_user_id", table_name="profiles")
    op.drop_table("profiles")
