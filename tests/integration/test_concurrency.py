"""Race conditions on real Postgres: the DB constraints, not app-level checks, must hold."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app import services
from app.models import URL

pytestmark = pytest.mark.integration

THREADS = 30


def run_concurrently(sessionmaker, fn):
    """Run `fn(session)` in THREADS threads released at the same instant."""
    barrier = threading.Barrier(THREADS)

    def worker(_):
        with sessionmaker() as session:
            barrier.wait()
            try:
                return ("ok", fn(session))
            except Exception as exc:  # noqa: BLE001 - we assert on the type below
                return ("err", exc)

    with ThreadPoolExecutor(THREADS) as pool:
        return list(pool.map(worker, range(THREADS)))


def test_same_url_concurrently_yields_one_row_and_one_code(pg_sessionmaker):
    # Repeat with fresh URLs: a single lucky run could miss a race.
    for i in range(10):
        url = f"https://example.com/race/{i}"
        results = run_concurrently(
            pg_sessionmaker, lambda s, url=url: services.create_url(s, url, 8).short_code
        )
        assert all(kind == "ok" for kind, _ in results), results
        assert len({code for _, code in results}) == 1, "different codes for the same URL"

        with pg_sessionmaker() as s:
            rows = s.scalar(select(func.count()).select_from(URL).where(URL.target_url == url))
        assert rows == 1


def test_same_alias_concurrently_has_exactly_one_winner(pg_sessionmaker):
    results = run_concurrently(
        pg_sessionmaker,
        lambda s: services.create_url(s, "https://example.com/a", 8, alias="contested").short_code,
    )
    winners = [r for kind, r in results if kind == "ok"]
    losers = [r for kind, r in results if kind == "err"]
    assert winners == ["contested"]
    assert len(losers) == THREADS - 1
    assert all(isinstance(e, services.AliasTakenError) for e in losers)


def test_many_distinct_urls_concurrently_all_succeed_with_unique_codes(pg_sessionmaker):
    counter = iter(range(10_000))
    lock = threading.Lock()

    def create(s):
        with lock:
            n = next(counter)
        return services.create_url(s, f"https://example.com/distinct/{n}", 8).short_code

    results = run_concurrently(pg_sessionmaker, create)
    codes = [c for kind, c in results if kind == "ok"]
    assert len(codes) == THREADS
    assert len(set(codes)) == THREADS
