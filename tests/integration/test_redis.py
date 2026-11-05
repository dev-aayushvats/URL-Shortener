"""RedisCache and the rate limiter against REAL Redis."""

import time

import pytest
import redis

from app.cache import RedisCache

pytestmark = [pytest.mark.integration, pytest.mark.needs_redis]


@pytest.fixture
def raw(redis_url):
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    yield client
    client.close()


def test_set_get_roundtrip_with_default_ttl(redis_url, raw):
    cache = RedisCache(redis_url, ttl_seconds=100)
    cache.set("abc", "https://example.com")
    assert cache.get("abc") == "https://example.com"
    assert 95 <= raw.ttl("abc") <= 100


def test_explicit_ttl_is_capped_by_default_ttl(redis_url, raw):
    cache = RedisCache(redis_url, ttl_seconds=100)
    cache.set("short", "u", ttl=30)  # shorter than default: honoured
    cache.set("long", "u", ttl=10_000)  # longer than default: capped
    assert 25 <= raw.ttl("short") <= 30
    assert 95 <= raw.ttl("long") <= 100


def test_non_positive_ttl_is_not_cached(redis_url, raw):
    RedisCache(redis_url, 100).set("gone", "u", ttl=0)
    assert raw.exists("gone") == 0


def test_miss_returns_none(redis_url):
    assert RedisCache(redis_url, 100).get("nope") is None


def test_incr_counts_and_sets_expiry_once(redis_url, raw):
    cache = RedisCache(redis_url, 100)
    assert cache.incr("rl:test", 60) == 1
    first_ttl = raw.ttl("rl:test")
    assert 55 <= first_ttl <= 60
    time.sleep(1.1)
    assert cache.incr("rl:test", 60) == 2
    # EXPIRE NX: the window must NOT slide forward on later hits.
    assert raw.ttl("rl:test") < first_ttl


def test_incr_is_atomic_under_threads(redis_url):
    from concurrent.futures import ThreadPoolExecutor

    cache = RedisCache(redis_url, 100)
    with ThreadPoolExecutor(20) as pool:
        counts = list(pool.map(lambda _: cache.incr("rl:atomic", 60), range(200)))
    assert sorted(counts) == list(range(1, 201))  # no lost or duplicated counts
