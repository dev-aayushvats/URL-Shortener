import hashlib
import secrets
import string

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import URL

ALPHABET = string.ascii_letters + string.digits  # base62
MAX_ATTEMPTS = 5


def generate_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def get_or_create_url(db: Session, target_url: str, code_length: int) -> URL:
    """Return the existing mapping for `target_url`, or create one.

    Safe under concurrency: uniqueness is enforced by DB constraints, not by a
    check-then-insert. On IntegrityError we distinguish "someone else just
    inserted this URL" (return theirs) from "short code collision" (retry).
    """
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
