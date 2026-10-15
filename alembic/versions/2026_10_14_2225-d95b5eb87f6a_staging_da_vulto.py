"""staging da Vulto: schema legado_vulto

O schema guarda a cópia crua dos dados da Vulto (vulto.db, planilhas e o export do atendimento),
primeira camada da migração. As tabelas de dentro espelham as origens e são recriadas a cada carga
pelo pipeline (python -m src.migracao_vulto --dominio staging), por isso não ficam aqui.
As ocorrências passam a aceitar o domínio "staging".

Revision ID: d95b5eb87f6a
Revises: e0e3ab34ad9d
Create Date: 2026-10-14 22:25:07.722858

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d95b5eb87f6a"
down_revision: str | Sequence[str] | None = "e0e3ab34ad9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOMINIOS = "'lojas', 'produtos', 'clientes', 'usuarios', 'vendas', 'estoque', 'fidelidade', 'atendimento'"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS legado_vulto")
    op.drop_constraint("ck_migracao_ocorrencias_dominio", "migracao_ocorrencias", type_="check")
    op.create_check_constraint("ck_migracao_ocorrencias_dominio", "migracao_ocorrencias", f"dominio IN ('staging', {_DOMINIOS})")


def downgrade() -> None:
    """Apaga o staging inteiro (é só a cópia do legado; o legado continua intacto)."""
    op.execute("DELETE FROM migracao_ocorrencias WHERE dominio = 'staging'")
    op.drop_constraint("ck_migracao_ocorrencias_dominio", "migracao_ocorrencias", type_="check")
    op.create_check_constraint("ck_migracao_ocorrencias_dominio", "migracao_ocorrencias", f"dominio IN ({_DOMINIOS})")
    op.execute("DROP SCHEMA IF EXISTS legado_vulto CASCADE")
