"""Integration tests against REAL PostgreSQL.

Enabled by setting TEST_DATABASE_URL, e.g.
    export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/url_shortener_test
    pytest -m integration
They are skipped otherwise. The target database name must contain "test" because
these tests DROP everything in the public schema.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def pytest_collection_modifyitems(config, items):
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set (needs real Postgres)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def pg_url():
    assert TEST_DATABASE_URL
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1]
    assert "test" in db_name, f"Refusing to wipe non-test database {db_name!r}"
    return TEST_DATABASE_URL


@pytest.fixture
def pg_engine(pg_url):
    engine = create_engine(pg_url, pool_size=40, max_overflow=0)
    with engine.begin() as conn:  # start every test from an empty schema
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


@pytest.fixture
def pg_sessionmaker(pg_engine):
    from app.database import Base

    Base.metadata.create_all(pg_engine)
    return sessionmaker(bind=pg_engine, autoflush=False)
