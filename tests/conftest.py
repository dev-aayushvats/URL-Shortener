import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["BASE_URL"] = "http://testserver"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import get_cache
from app.database import Base, get_db
from app.main import app


class FakeCache:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self.counters: dict[str, int] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value
        self.ttls[key] = ttl

    def incr(self, key, window_seconds):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]


@pytest.fixture
def cache():
    return FakeCache()


@pytest.fixture
def client(cache):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_cache] = lambda: cache
    yield TestClient(app)
    app.dependency_overrides.clear()
