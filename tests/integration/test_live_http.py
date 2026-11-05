"""The real app (uvicorn) over real HTTP, backed by real Postgres and Redis."""

import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import redis
from sqlalchemy import func, select

from app.models import URL

pytestmark = [pytest.mark.integration, pytest.mark.needs_redis]

N = 30


def burst(fn, n=N):
    """Run fn(i) in n threads released simultaneously."""
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(worker, range(n)))


def test_full_flow_create_redirect_cache(live_server, redis_url):
    base = live_server()
    r = httpx.post(f"{base}/shorten", json={"target_url": "https://example.com/flow"})
    assert r.status_code == 200
    code = r.json()["short_code"]

    redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    assert redis_client.get(code) is None  # not cached until first redirect

    hit = httpx.get(f"{base}/{code}", follow_redirects=False)
    assert hit.status_code == 302
    assert hit.headers["location"] == "https://example.com/flow"
    assert redis_client.get(code) == "https://example.com/flow"
    assert 86_000 < redis_client.ttl(code) <= 86_400


def test_http_race_same_url_one_row_one_code(live_server, pg_reader):
    base = live_server()
    url = "https://example.com/http-race"
    with httpx.Client(timeout=30, limits=httpx.Limits(max_connections=N)) as client:
        results = burst(lambda _: client.post(f"{base}/shorten", json={"target_url": url}))
    assert {r.status_code for r in results} == {200}
    assert len({r.json()["short_code"] for r in results}) == 1
    with pg_reader() as s:
        assert s.scalar(select(func.count()).select_from(URL).where(URL.target_url == url)) == 1


def test_http_race_same_alias_one_winner(live_server):
    base = live_server()
    with httpx.Client(timeout=30, limits=httpx.Limits(max_connections=N)) as client:
        results = burst(
            lambda _: client.post(
                f"{base}/shorten",
                json={"target_url": "https://example.com/alias", "custom_alias": "contested"},
            )
        )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200] + [409] * (N - 1)


def test_rate_limit_is_exact_under_concurrency(live_server):
    """50 simultaneous requests against a limit of 10: exactly 10 may pass (atomic INCR)."""
    base = live_server(rate_limit=10)
    n = 50
    with httpx.Client(timeout=30, limits=httpx.Limits(max_connections=n)) as client:
        results = burst(
            lambda i: client.post(f"{base}/shorten", json={"target_url": f"https://e.com/{i}"}),
            n=n,
        )
    statuses = [r.status_code for r in results]
    assert statuses.count(200) == 10
    assert statuses.count(429) == 40
    assert all("retry-after" in r.headers for r in results if r.status_code == 429)


def test_redirect_still_works_when_cache_entry_missing(live_server, redis_url):
    base = live_server()
    code = httpx.post(f"{base}/shorten", json={"target_url": "https://example.com/m"}).json()[
        "short_code"
    ]
    httpx.get(f"{base}/{code}", follow_redirects=False)
    redis.Redis.from_url(redis_url).flushdb()  # simulate eviction/restart of the cache
    assert httpx.get(f"{base}/{code}", follow_redirects=False).status_code == 302
