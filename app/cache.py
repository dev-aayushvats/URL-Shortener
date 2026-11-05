"""Thin Redis wrapper. The cache is an optimisation: every failure degrades to a miss."""

import logging
from typing import Protocol

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


class RedisCache:
    def __init__(self, url: str, ttl_seconds: int) -> None:
        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        self._ttl = ttl_seconds

    def get(self, key: str) -> str | None:
        try:
            return self._client.get(key)
        except redis.RedisError:
            logger.warning("Redis GET failed; treating as cache miss", exc_info=True)
            return None

    def set(self, key: str, value: str) -> None:
        try:
            self._client.set(key, value, ex=self._ttl)
        except redis.RedisError:
            logger.warning("Redis SET failed; continuing without cache", exc_info=True)


def get_cache() -> Cache:
    """FastAPI dependency (overridable in tests)."""
    global _cache
    if _cache is None:
        s = get_settings()
        _cache = RedisCache(s.redis_url, s.cache_ttl_seconds)
    return _cache


_cache: RedisCache | None = None
