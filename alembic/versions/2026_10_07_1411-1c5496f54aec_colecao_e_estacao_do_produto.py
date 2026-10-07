"""coleção (gênero) e estação do produto: só os valores da vitrine

Revision ID: 1c5496f54aec
Revises: bbfdeb8e8e3f
Create Date: 2026-10-07 14:11:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "1c5496f54aec"
down_revision: str | Sequence[str] | None = "bbfdeb8e8e3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Produtos antigos sem estação passam a atemporais (aparecem em qualquer filtro de estação)
    op.execute("UPDATE produtos SET estacao = 'Atemporal' WHERE estacao IS NULL")
    op.create_check_constraint("ck_produtos_genero", "produtos", "genero IS NULL OR genero IN ('Masculino', 'Feminino')")
    op.create_check_constraint(
        "ck_produtos_estacao", "produtos", "estacao IS NULL OR estacao IN ('Inverno', 'Verão', 'Atemporal')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_produtos_estacao", "produtos", type_="check")
    op.drop_constraint("ck_produtos_genero", "produtos", type_="check")
