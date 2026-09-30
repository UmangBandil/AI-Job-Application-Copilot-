"""convert resume_chunks.embedding to pgvector vector(384)

Revision ID: 0002_pgvector_embedding
Revises: 0001_baseline
Create Date: 2026-09-30

Backfills existing float-array embeddings into the new typed column, so
stored resume data survives the conversion. Adds an HNSW index for
cosine similarity search.
"""

from alembic import op

revision = "0002_pgvector_embedding"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("ALTER TABLE resume_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector(384)")

    # Backfill: convert float arrays (only exact 384-dim ones) to vector literals.
    op.execute(
        """
        UPDATE resume_chunks
        SET embedding_vec = (
            SELECT ('[' || string_agg(value::text, ',' ORDER BY ord) || ']')::vector
            FROM unnest(embedding) WITH ORDINALITY AS t(value, ord)
        )
        WHERE embedding IS NOT NULL AND array_length(embedding, 1) = 384
        """
    )

    op.drop_column("resume_chunks", "embedding")
    op.execute("ALTER TABLE resume_chunks RENAME COLUMN embedding_vec TO embedding")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_resume_chunks_embedding "
        "ON resume_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resume_chunks_embedding")
    op.execute("ALTER TABLE resume_chunks ADD COLUMN embedding_arr double precision[]")
    op.execute(
        """
        UPDATE resume_chunks
        SET embedding_arr = ARRAY(
            SELECT value::double precision
            FROM unnest(embedding::real[]) WITH ORDINALITY AS t(value, ord)
            ORDER BY ord
        )
        WHERE embedding IS NOT NULL
        """
    )
    op.drop_column("resume_chunks", "embedding")
    op.execute("ALTER TABLE resume_chunks RENAME COLUMN embedding_arr TO embedding")
