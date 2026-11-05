"""Alembic migrations on real Postgres."""

import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from app import models  # noqa: F401
from app.database import Base

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def alembic(pg_url, *args):
    import os

    env = {**os.environ, "DATABASE_URL": pg_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result


def test_upgrade_head_on_empty_database_matches_models(pg_url, pg_engine):
    """Running every migration must produce exactly the schema the models declare."""
    alembic(pg_url, "upgrade", "head")
    with pg_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"migrations and models have drifted: {diff}"


def test_upgrade_preserves_existing_rows(pg_url, pg_engine):
    alembic(pg_url, "upgrade", "0001")
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO urls (short_code, target_url, target_hash) "
                "VALUES ('old12345', 'https://old.example', 'h1')"
            )
        )
    alembic(pg_url, "upgrade", "head")
    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT target_url, expires_at FROM urls WHERE short_code='old12345'")
        ).one()
    assert row.target_url == "https://old.example"
    assert row.expires_at is None


def test_downgrade_keeps_default_links_and_drops_custom_ones(pg_url, pg_engine):
    alembic(pg_url, "upgrade", "head")
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO urls (short_code, target_url, target_hash) "
                "VALUES ('plain1', 'https://a.example', 'hash-a')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO urls (short_code, target_url) VALUES ('custom-alias', 'https://b.example')"
            )
        )
    alembic(pg_url, "downgrade", "0001")
    with pg_engine.connect() as conn:
        codes = {r[0] for r in conn.execute(text("SELECT short_code FROM urls"))}
    assert codes == {"plain1"}
    alembic(pg_url, "upgrade", "head")  # and back up again
