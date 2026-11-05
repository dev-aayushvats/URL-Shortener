from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class URL(Base):
    __tablename__ = "urls"

    short_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of target_url, set ONLY for default links (no alias, no expiry).
    # The UNIQUE constraint makes "one default short code per URL" safe under
    # concurrency; custom/expiring links store NULL (multiple NULLs are allowed).
    target_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
