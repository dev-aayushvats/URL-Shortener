"""Fixed-window rate limiter backed by Redis (fails open if Redis is down)."""

import time

from fastapi import Depends, HTTPException, Request

from app.cache import Cache, get_cache
from app.config import Settings, get_settings

WINDOW_SECONDS = 60


def rate_limit(
    request: Request,
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> None:
    # NOTE: behind a reverse proxy, run uvicorn with --proxy-headers and
    # --forwarded-allow-ips=<proxy ip> so request.client is the real client.
    client_ip = request.client.host if request.client else "unknown"
    now = int(time.time())
    bucket = now // WINDOW_SECONDS
    count = cache.incr(f"rl:shorten:{client_ip}:{bucket}", WINDOW_SECONDS)
    if count is not None and count > settings.rate_limit_per_minute:
        retry_after = WINDOW_SECONDS - (now % WINDOW_SECONDS)
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )
