from datetime import timedelta
from unittest.mock import patch

import redis

from app import services
from app.cache import RedisCache
from app.config import Settings, get_settings
from app.main import app

URL = "https://example.com/page"


def post(client, **body):
    return client.post("/shorten", json={"target_url": URL, **body})


# ---- custom alias
def test_custom_alias_redirects(client):
    r = post(client, custom_alias="my-link")
    assert r.status_code == 200
    assert r.json()["short_code"] == "my-link"
    assert client.get("/my-link", follow_redirects=False).headers["location"] == URL


def test_alias_taken_returns_409(client):
    assert post(client, custom_alias="taken").status_code == 200
    r = client.post(
        "/shorten", json={"target_url": "https://other.example/", "custom_alias": "taken"}
    )
    assert r.status_code == 409


def test_alias_does_not_dedupe_or_break_default_link(client):
    default = post(client).json()["short_code"]
    assert post(client, custom_alias="vanity").json()["short_code"] == "vanity"
    assert post(client).json()["short_code"] == default


def test_invalid_alias_rejected(client):
    assert post(client, custom_alias="a b").status_code == 422
    assert post(client, custom_alias="ab").status_code == 422


def test_reserved_alias_rejected(client):
    assert post(client, custom_alias="health").status_code == 422
    assert post(client, custom_alias="DOCS").status_code == 422


# ---- expiry
def test_expiry_sets_expires_at_and_bounds_cache_ttl(client, cache):
    r = post(client, expires_in_seconds=120)
    body = r.json()
    assert body["expires_at"] is not None
    client.get(f"/{body['short_code']}", follow_redirects=False)
    assert 0 < cache.ttls[body["short_code"]] <= 120


def test_expired_link_returns_410(client):
    code = post(client, expires_in_seconds=120).json()["short_code"]
    future = services.utcnow() + timedelta(seconds=121)
    with patch("app.main.services.utcnow", return_value=future):
        assert client.get(f"/{code}").status_code == 410


def test_unexpired_link_still_works(client):
    code = post(client, expires_in_seconds=3600).json()["short_code"]
    assert client.get(f"/{code}", follow_redirects=False).status_code == 302


def test_expiry_bounds_validated(client):
    assert post(client, expires_in_seconds=5).status_code == 422  # below minimum
    assert post(client, expires_in_seconds=10**9).status_code == 422  # above maximum
    assert post(client, expires_in_seconds=-1).status_code == 422


def test_expiring_links_are_not_deduplicated(client):
    a = post(client, expires_in_seconds=300).json()["short_code"]
    b = post(client, expires_in_seconds=300).json()["short_code"]
    assert a != b


# ---- rate limiting
def test_rate_limit_returns_429_with_retry_after(client):
    app.dependency_overrides[get_settings] = lambda: Settings(rate_limit_per_minute=3)
    codes = [post(client).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert 1 <= int(post(client).headers["retry-after"]) <= 60


def test_rate_limit_does_not_apply_to_redirects(client):
    app.dependency_overrides[get_settings] = lambda: Settings(rate_limit_per_minute=1)
    code = post(client).json()["short_code"]
    assert all(client.get(f"/{code}", follow_redirects=False).status_code == 302 for _ in range(5))


def test_rate_limit_fails_open_when_redis_down():
    cache = RedisCache("redis://localhost:1/0", 60)
    with patch.object(cache._client, "pipeline", side_effect=redis.ConnectionError):
        assert cache.incr("k", 60) is None
