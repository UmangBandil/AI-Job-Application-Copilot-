"""create application_questions (question/answer memory)

Revision ID: 0004_create_application_questions
Revises: 0003_create_profiles
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_create_application_questions"
down_revision = "0003_create_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "application_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.String(500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("context", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_application_questions_user_id", "application_questions", ["user_id"])
    op.execute(
        "CREATE INDEX ix_application_questions_normalized "
        "ON application_questions (user_id, normalized_question)"
    )

    op.execute("ALTER TABLE application_questions ADD COLUMN embedding_vec vector(384)")
    op.execute("ALTER TABLE application_questions RENAME COLUMN embedding_vec TO embedding")
    op.execute(
        "CREATE INDEX ix_application_questions_embedding "
        "ON application_questions USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_application_questions_embedding")
    op.execute("DROP INDEX IF EXISTS ix_application_questions_normalized")
    op.drop_index("ix_application_questions_user_id", table_name="application_questions")
    op.drop_table("application_questions")
