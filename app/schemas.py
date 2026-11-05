from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

RESERVED_ALIASES = {"health", "docs", "redoc", "openapi", "shorten", "static", "api"}


class ShortenRequest(BaseModel):
    target_url: HttpUrl
    custom_alias: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{3,32}$",
        description="Optional custom short code (3-32 chars: letters, digits, _ or -).",
    )
    expires_in_seconds: int | None = Field(
        default=None, gt=0, description="Optional lifetime of the link in seconds."
    )


class ShortenResponse(BaseModel):
    short_code: str
    target_url: str
    short_url: str
    expires_at: datetime | None = None
