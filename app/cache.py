"""Thin Redis wrapper. The cache is an optimisation: every failure degrades to a miss."""

import logging
from typing import Protocol

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
    def incr(self, key: str, window_seconds: int) -> int | None: ...


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

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        # Never cache longer than the caller allows (e.g. a link's remaining lifetime).
        ex = min(ttl, self._ttl) if ttl is not None else self._ttl
        if ex <= 0:
            return
        try:
            self._client.set(key, value, ex=ex)
        except redis.RedisError:
            logger.warning("Redis SET failed; continuing without cache", exc_info=True)

    def incr(self, key: str, window_seconds: int) -> int | None:
        """Atomically increment a counter that expires after the window.

        Returns None if Redis is unavailable (callers should fail open).
        """
        try:
            pipe = self._client.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            return int(pipe.execute()[0])
        except redis.RedisError:
            logger.warning("Redis INCR failed; rate limiting skipped", exc_info=True)
            return None


def get_cache() -> Cache:
    """FastAPI dependency (overridable in tests)."""
    global _cache
    if _cache is None:
        s = get_settings()
        _cache = RedisCache(s.redis_url, s.cache_ttl_seconds)
    return _cache


_cache: RedisCache | None = None
