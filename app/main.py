import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import models, services
from app.cache import Cache, get_cache
from app.config import Settings, get_settings
from app.database import get_db
from app.schemas import ShortenRequest, ShortenResponse

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


@app.post("/shorten", response_model=ShortenResponse, tags=["urls"])
def shorten(
    payload: ShortenRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ShortenResponse:
    """Create (or fetch the existing) short URL for `target_url`."""
    record = services.get_or_create_url(db, str(payload.target_url), settings.short_code_length)
    return ShortenResponse(
        short_code=record.short_code,
        target_url=record.target_url,
        short_url=f"{settings.base_url.rstrip('/')}/{record.short_code}",
    )


@app.get("/{short_code}", tags=["urls"])
def redirect(
    short_code: str = PathParam(pattern=r"^[A-Za-z0-9]{1,16}$"),
    db: Session = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> RedirectResponse:
    """Redirect to the original URL (cache-aside: Redis, then Postgres)."""
    target = cache.get(short_code)
    if target is None:
        target = db.scalar(select(models.URL.target_url).where(models.URL.short_code == short_code))
        if target is None:
            raise HTTPException(status_code=404, detail="Short URL not found")
        cache.set(short_code, target)
    # 302 (not 301) so browsers don't cache the redirect, keeping future analytics/expiry possible.
    return RedirectResponse(target, status_code=302)
