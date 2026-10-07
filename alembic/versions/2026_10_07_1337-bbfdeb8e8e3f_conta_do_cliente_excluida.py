"""conta do cliente excluída pelo próprio cliente (excluido_em)

Revision ID: bbfdeb8e8e3f
Revises: 52b6420b4b4c
Create Date: 2026-10-07 13:37:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bbfdeb8e8e3f"
down_revision: str | Sequence[str] | None = "52b6420b4b4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clientes", sa.Column("excluido_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("clientes", "excluido_em")
