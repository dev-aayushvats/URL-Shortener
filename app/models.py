from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class URL(Base):
    __tablename__ = "urls"

    short_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of target_url. Indexing a fixed-size hash (instead of an arbitrarily
    # long URL) keeps the index small and gives us a UNIQUE constraint that makes
    # "one short code per URL" safe under concurrent requests.
    target_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
