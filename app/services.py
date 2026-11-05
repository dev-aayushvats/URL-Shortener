import hashlib
import secrets
import string
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import URL

ALPHABET = string.ascii_letters + string.digits  # base62
MAX_ATTEMPTS = 5


class AliasTakenError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_aware(dt: datetime) -> datetime:
    """DBs like SQLite return naive datetimes; we always store UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def is_expired(record: URL, now: datetime | None = None) -> bool:
    return record.expires_at is not None and as_aware(record.expires_at) <= (now or utcnow())


def generate_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def create_url(
    db: Session,
    target_url: str,
    code_length: int,
    alias: str | None = None,
    expires_at: datetime | None = None,
) -> URL:
    """Create a short URL.

    - Default links (no alias/expiry) are deduplicated: the same URL always maps to
      the same code, enforced by a UNIQUE hash (safe under concurrency).
    - Custom/expiring links always create a new mapping (raises AliasTakenError if
      the alias is in use).
    """
    if alias is None and expires_at is None:
        return _get_or_create_default(db, target_url, code_length)

    for _ in range(1 if alias else MAX_ATTEMPTS):
        record = URL(
            short_code=alias or generate_code(code_length),
            target_url=target_url,
            expires_at=expires_at,
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if alias:
                raise AliasTakenError(alias) from None
            continue  # random code collision: retry
        return record
    raise RuntimeError("Could not allocate a unique short code")


def _get_or_create_default(db: Session, target_url: str, code_length: int) -> URL:
    """On IntegrityError, either someone just inserted this URL (return theirs)
    or the random code collided (retry)."""
    target_hash = hash_url(target_url)

    for _ in range(MAX_ATTEMPTS):
        existing = db.scalar(select(URL).where(URL.target_hash == target_hash))
        if existing:
            return existing

        record = URL(
            short_code=generate_code(code_length),
            target_url=target_url,
            target_hash=target_hash,
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        return record

    raise RuntimeError("Could not allocate a unique short code")
