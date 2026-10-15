"""custo médio e variação ativa

- variacoes.custo_medio: custo médio ponderado das entradas (regra do Financeiro), ao lado do
  preco_custo (último custo, regra de Compras).
- variacoes.ativa: variação descontinuada (cor ou tamanho que saiu de linha) sem desativar o produto.
  Todas as existentes ficam ativas.

Revision ID: b14cf28501fc
Revises: d95b5eb87f6a
Create Date: 2026-10-14 22:44:17.866388

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b14cf28501fc"
down_revision: str | Sequence[str] | None = "d95b5eb87f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("variacoes", sa.Column("custo_medio", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("variacoes", sa.Column("ativa", sa.Boolean(), server_default="true", nullable=False))
    op.create_check_constraint("ck_variacoes_custo_medio", "variacoes", "custo_medio IS NULL OR custo_medio >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_variacoes_custo_medio", "variacoes", type_="check")
    op.drop_column("variacoes", "ativa")
    op.drop_column("variacoes", "custo_medio")
