"""add expires_at, allow custom aliases

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("urls", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("urls", "target_hash", existing_type=sa.String(64), nullable=True)
    op.alter_column("urls", "short_code", existing_type=sa.String(16), type_=sa.String(32))


def downgrade() -> None:
    # Custom/expiring rows have NULL hashes; they can't satisfy the old NOT NULL schema.
    op.execute("DELETE FROM urls WHERE target_hash IS NULL")
    op.alter_column("urls", "short_code", existing_type=sa.String(32), type_=sa.String(16))
    op.alter_column("urls", "target_hash", existing_type=sa.String(64), nullable=False)
    op.drop_column("urls", "expires_at")
