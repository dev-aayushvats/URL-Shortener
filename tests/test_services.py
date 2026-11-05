"""Unit tests for the retry/collision paths in app.services (SQLite, no Docker)."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import services
from app.database import Base
from app.models import URL


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def test_default_link_retries_on_random_code_collision(db):
    db.add(URL(short_code="AAAAAAAA", target_url="https://taken.example", target_hash="x"))
    db.commit()
    # First generated code collides with the existing row; the second is free.
    with patch.object(services, "generate_code", side_effect=["AAAAAAAA", "BBBBBBBB"]):
        record = services.create_url(db, "https://new.example", 8)
    assert record.short_code == "BBBBBBBB"


def test_expiring_link_retries_on_random_code_collision(db):
    db.add(URL(short_code="AAAAAAAA", target_url="https://taken.example", target_hash="x"))
    db.commit()
    with patch.object(services, "generate_code", side_effect=["AAAAAAAA", "CCCCCCCC"]):
        record = services.create_url(db, "https://new.example", 8, expires_at=services.utcnow())
    assert record.short_code == "CCCCCCCC"


def test_gives_up_after_max_attempts(db):
    db.add(URL(short_code="AAAAAAAA", target_url="https://taken.example", target_hash="x"))
    db.commit()
    with (
        patch.object(services, "generate_code", return_value="AAAAAAAA"),
        pytest.raises(RuntimeError),
    ):
        services.create_url(db, "https://new.example", 8)
    assert db.scalar(select(func.count()).select_from(URL)) == 1  # nothing half-written


def test_alias_taken_raises(db):
    services.create_url(db, "https://a.example", 8, alias="mine")
    with pytest.raises(services.AliasTakenError):
        services.create_url(db, "https://b.example", 8, alias="mine")


def test_is_expired_handles_naive_datetimes(db):
    # SQLite returns naive datetimes; we treat them as UTC.
    record = URL(short_code="x", target_url="u", expires_at=services.utcnow().replace(tzinfo=None))
    assert services.is_expired(record) is True
