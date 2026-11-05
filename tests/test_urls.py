from unittest.mock import patch

import redis

from app.cache import RedisCache

URL = "https://example.com/some/very/long/path?q=1"


def test_shorten_creates_code(client):
    r = client.post("/shorten", json={"target_url": URL})
    assert r.status_code == 200
    body = r.json()
    assert len(body["short_code"]) == 8
    assert body["short_url"] == f"http://testserver/{body['short_code']}"


def test_shorten_is_idempotent(client):
    a = client.post("/shorten", json={"target_url": URL}).json()
    b = client.post("/shorten", json={"target_url": URL}).json()
    assert a["short_code"] == b["short_code"]


def test_shorten_rejects_invalid_url(client):
    assert client.post("/shorten", json={"target_url": "not a url"}).status_code == 422


def test_redirect_and_cache_fill(client, cache):
    code = client.post("/shorten", json={"target_url": URL}).json()["short_code"]
    r = client.get(f"/{code}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == URL
    assert cache.store[code] == URL


def test_redirect_served_from_cache(client, cache):
    cache.store["abc123"] = "https://cached.example/"
    r = client.get("/abc123", follow_redirects=False)
    assert r.headers["location"] == "https://cached.example/"


def test_unknown_code_404(client):
    assert client.get("/doesnotexist").status_code == 404


def test_invalid_code_format_422(client):
    assert client.get("/bad-code!").status_code == 422


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_redis_failure_degrades_gracefully():
    cache = RedisCache("redis://localhost:1/0", 60)
    with patch.object(cache._client, "get", side_effect=redis.ConnectionError):
        assert cache.get("x") is None
    with patch.object(cache._client, "set", side_effect=redis.ConnectionError):
        cache.set("x", "y")  # must not raise
