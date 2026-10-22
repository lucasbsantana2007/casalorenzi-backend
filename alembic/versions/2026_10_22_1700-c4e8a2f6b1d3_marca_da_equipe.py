"""marca da equipe

Cada funcionário passa a trabalhar com uma marca: LORENZI, VULTO ou GRUPO (só Administrador, que vê
as duas). Quem não é do grupo não vê nem altera nada da outra marca no painel.

Os que já existem: o Administrador vira GRUPO; Lojista e Operador ficam com a marca da loja deles
(sem loja, LORENZI, a marca de tudo que existia antes da união).

Revision ID: c4e8a2f6b1d3
Revises: b7a1c3d9e2f4
Create Date: 2026-10-22 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a2f6b1d3"
down_revision: str | Sequence[str] | None = "b7a1c3d9e2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("marca", sa.String(length=10), server_default="LORENZI", nullable=False))
    op.execute("UPDATE usuarios SET marca = 'GRUPO' WHERE papel = 'ADMINISTRADOR'")
    op.execute(
        "UPDATE usuarios u SET marca = l.marca FROM lojas l WHERE u.loja_id = l.id AND u.papel <> 'ADMINISTRADOR'"
    )
    op.create_check_constraint("ck_usuarios_marca", "usuarios", "marca IN ('LORENZI', 'VULTO', 'GRUPO')")
    op.create_check_constraint("ck_usuarios_grupo_so_admin", "usuarios", "marca <> 'GRUPO' OR papel = 'ADMINISTRADOR'")


def downgrade() -> None:
    op.drop_constraint("ck_usuarios_grupo_so_admin", "usuarios", type_="check")
    op.drop_constraint("ck_usuarios_marca", "usuarios", type_="check")
    op.drop_column("usuarios", "marca")
