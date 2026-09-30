"""Programmatic Alembic migration runner used by the app lifespan.

Alembic itself is synchronous; migrations run once at startup, before the
server begins accepting requests. A Postgres advisory lock makes it safe
when multiple gunicorn workers start concurrently — losers block until the
winner finishes, then find the schema already at head and no-op.

Databases created by create_all before migrations existed are detected
(tables present, no alembic_version) and stamped at the baseline revision
before upgrading.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend
MIGRATION_LOCK_KEY = 727447220  # arbitrary app-specific advisory lock id
BASELINE_REVISION = "0001_baseline"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL_SYNC)
    return cfg


def _upgrade_head() -> None:
    command.upgrade(_alembic_config(), "head")


def stamp_head() -> None:
    command.stamp(_alembic_config(), "head")


def run_migrations() -> None:
    """Apply pending migrations, serialized across workers/processes."""
    engine = create_engine(get_settings().DATABASE_URL_SYNC)
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_KEY})"))
            try:
                conn.commit()
                insp = inspect(conn)
                if not insp.has_table("alembic_version"):
                    if insp.has_table("users"):
                        # Legacy database created by create_all before migrations
                        # existed — its schema already equals the baseline.
                        command.stamp(_alembic_config(), BASELINE_REVISION)
                _upgrade_head()
            finally:
                conn.execute(text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_KEY})"))
                conn.commit()
    finally:
        engine.dispose()
