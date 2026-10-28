"""automacao encerrar_whatsapp

Decisão 115 (docs/registro_decisoes_e4.md): a automação encerrar_whatsapp fecha o chamado do WhatsApp quando o
cliente fica 4 horas sem responder à equipe. Só amplia a lista de nomes aceitos em execucoes_automacao; o downgrade
apaga as execuções dela e volta a lista anterior.

Revision ID: a7c3e5f19b28
Revises: d8a3f1c26b47
Create Date: 2026-10-28 17:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c3e5f19b28'
down_revision: str | Sequence[str] | None = 'd8a3f1c26b47'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTOMACOES_ANTES = (
    "'estoque_baixo', 'estoque_parado', 'sugestoes_transferencia', 'pontos_a_vencer', 'aviso_pontos', "
    "'aviso_estoque', 'lembrete_sacola', 'limpeza_conversas'"
)
AUTOMACOES_DEPOIS = AUTOMACOES_ANTES + ", 'encerrar_whatsapp'"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('ck_execucoes_automacao_automacao', 'execucoes_automacao', type_='check')
    op.create_check_constraint(
        'ck_execucoes_automacao_automacao', 'execucoes_automacao', f'automacao IN ({AUTOMACOES_DEPOIS})'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM execucoes_automacao WHERE automacao = 'encerrar_whatsapp'")
    op.drop_constraint('ck_execucoes_automacao_automacao', 'execucoes_automacao', type_='check')
    op.create_check_constraint(
        'ck_execucoes_automacao_automacao', 'execucoes_automacao', f'automacao IN ({AUTOMACOES_ANTES})'
    )
