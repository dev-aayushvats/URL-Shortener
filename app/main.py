import logging
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models, services
from app.cache import Cache, get_cache
from app.config import Settings, get_settings
from app.database import get_db
from app.ratelimit import rate_limit
from app.schemas import RESERVED_ALIASES, ShortenRequest, ShortenResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

INDEX_HTML = Path(__file__).parent / "static" / "index.html"


# Schema is managed by Alembic (`alembic upgrade head`), not created at import/startup.
app = FastAPI(title="URL Shortener", version="1.0.0")

# No CORS middleware: the UI is served from the same origin as the API.


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(INDEX_HTML, media_type="text/html")


@app.get("/health", tags=["ops"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post(
    "/shorten",
    response_model=ShortenResponse,
    tags=["urls"],
    dependencies=[Depends(rate_limit)],
    responses={409: {"description": "Alias already taken"}, 429: {"description": "Rate limited"}},
)
def shorten(
    payload: ShortenRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ShortenResponse:
    """Create a short URL.

    Without `custom_alias`/`expires_in_seconds`, the same URL always returns the same code.
    """
    alias = payload.custom_alias
    if alias and alias.lower() in RESERVED_ALIASES:
        raise HTTPException(status_code=422, detail="This alias is reserved")

    expires_at = None
    if payload.expires_in_seconds is not None:
        if (
            not settings.min_expiry_seconds
            <= payload.expires_in_seconds
            <= settings.max_expiry_seconds
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"expires_in_seconds must be between {settings.min_expiry_seconds} "
                    f"and {settings.max_expiry_seconds}"
                ),
            )
        expires_at = services.utcnow() + timedelta(seconds=payload.expires_in_seconds)

    try:
        record = services.create_url(
            db, str(payload.target_url), settings.short_code_length, alias, expires_at
        )
    except services.AliasTakenError:
        raise HTTPException(status_code=409, detail="Alias already taken") from None

    return ShortenResponse(
        short_code=record.short_code,
        target_url=record.target_url,
        short_url=f"{settings.base_url.rstrip('/')}/{record.short_code}",
        expires_at=record.expires_at,
    )


@app.get("/{short_code}", tags=["urls"], responses={410: {"description": "Link expired"}})
def redirect(
    short_code: str = PathParam(pattern=r"^[A-Za-z0-9_-]{1,32}$"),
    db: Session = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> RedirectResponse:
    """Redirect to the original URL (cache-aside: Redis, then Postgres)."""
    target = cache.get(short_code)
    if target is None:
        record = db.get(models.URL, short_code)
        if record is None:
            raise HTTPException(status_code=404, detail="Short URL not found")
        now = services.utcnow()
        if services.is_expired(record, now):
            raise HTTPException(status_code=410, detail="Short URL has expired")
        target = record.target_url
        # Cache no longer than the link's remaining lifetime so expiry is always honoured.
        remaining = (
            int((services.as_aware(record.expires_at) - now).total_seconds())
            if record.expires_at
            else None
        )
        cache.set(short_code, target, ttl=remaining)
    # 302 (not 301) so browsers don't cache the redirect, keeping future analytics/expiry possible.
    return RedirectResponse(target, status_code=302)
