"""Integration tests against REAL PostgreSQL.

Enabled by setting TEST_DATABASE_URL, e.g.
    export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/url_shortener_test
    pytest -m integration
They are skipped otherwise. The target database name must contain "test" because
these tests DROP everything in the public schema.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL")  # must use a non-zero DB index, e.g. /15
ROOT = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "integration" not in item.keywords:
            continue
        if not TEST_DATABASE_URL:
            item.add_marker(pytest.mark.skip(reason="TEST_DATABASE_URL not set (needs Postgres)"))
        elif "needs_redis" in item.keywords and not TEST_REDIS_URL:
            item.add_marker(pytest.mark.skip(reason="TEST_REDIS_URL not set (needs Redis)"))


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


@pytest.fixture
def pg_reader(pg_engine):
    """Sessions for inspecting a DB whose schema is managed by the live server's migrations."""
    return sessionmaker(bind=pg_engine, autoflush=False)


@pytest.fixture
def redis_url():
    assert TEST_REDIS_URL
    assert (
        not TEST_REDIS_URL.rstrip("/").endswith("/0")
        and TEST_REDIS_URL.rstrip("/").rsplit("/", 1)[-1].isdigit()
    ), "Use a non-zero Redis DB index (e.g. /15): these tests FLUSH it"
    import redis

    client = redis.Redis.from_url(TEST_REDIS_URL)
    client.flushdb()
    yield TEST_REDIS_URL
    client.flushdb()
    client.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(pg_url, pg_engine, redis_url):
    """Start the real app with uvicorn on a free port, against real Postgres + Redis.

    Use as `live_server(rate_limit=...)` -> base URL. Servers are stopped at teardown.
    """
    procs: list[subprocess.Popen] = []
    migrated = False

    def start(rate_limit: int = 1_000_000) -> str:
        nonlocal migrated
        port = _free_port()
        env = {
            **os.environ,
            "DATABASE_URL": pg_url,
            "REDIS_URL": redis_url,
            "BASE_URL": f"http://127.0.0.1:{port}",
            "RATE_LIMIT_PER_MINUTE": str(rate_limit),
        }
        if not migrated:
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
            )
            migrated = True
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=env,
        )
        procs.append(proc)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    return base
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("live server did not start")

    yield start
    for proc in procs:
        proc.terminate()
        proc.wait(timeout=10)
