"""produto removido do catálogo (removido_em)

Revision ID: 33ff73b0bdfa
Revises: 1c5496f54aec
Create Date: 2026-10-07 14:23:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "33ff73b0bdfa"
down_revision: str | Sequence[str] | None = "1c5496f54aec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("produtos", sa.Column("removido_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("produtos", "removido_em")
