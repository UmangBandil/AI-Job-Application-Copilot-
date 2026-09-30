"""Minimal Alembic script template (py templates)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = ${repr(revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | None = ${repr(branch_labels)}
depends_on: str | None = ${repr(depends_on)}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
