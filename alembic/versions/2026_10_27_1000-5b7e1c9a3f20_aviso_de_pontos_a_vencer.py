"""aviso de pontos a vencer

Decisão 82 (docs/registro_decisoes_e4.md): os clientes recebem um e-mail 30 dias antes de os pontos vencerem.
- avisos_pontos: um aviso por cliente e data de vencimento (a chave única impede o aviso repetido);
- execucoes_automacao passa a aceitar a automação aviso_pontos.
O downgrade apaga a tabela e o log das execuções dessa automação.

Revision ID: 5b7e1c9a3f20
Revises: 948372ce2329
Create Date: 2026-10-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b7e1c9a3f20'
down_revision: Union[str, Sequence[str], None] = '948372ce2329'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AUTOMACOES_ANTES = "'estoque_baixo', 'estoque_parado', 'sugestoes_transferencia', 'pontos_a_vencer', 'limpeza_conversas'"
AUTOMACOES_DEPOIS = (
    "'estoque_baixo', 'estoque_parado', 'sugestoes_transferencia', 'pontos_a_vencer', 'aviso_pontos', 'limpeza_conversas'"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('avisos_pontos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('vencimento', sa.Date(), nullable=False),
    sa.Column('pontos', sa.Integer(), nullable=False),
    sa.Column('modo', sa.String(length=5), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('sem_numeros', sa.Boolean(), nullable=False),
    sa.Column('enviado_em', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("modo IN ('REAL', 'TESTE')", name='ck_avisos_pontos_modo'),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cliente_id', 'vencimento', 'modo', name='uq_avisos_pontos_cliente_vencimento_modo')
    )
    op.create_index(op.f('ix_avisos_pontos_cliente_id'), 'avisos_pontos', ['cliente_id'], unique=False)
    op.create_index(op.f('ix_avisos_pontos_enviado_em'), 'avisos_pontos', ['enviado_em'], unique=False)
    op.drop_constraint('ck_execucoes_automacao_automacao', 'execucoes_automacao', type_='check')
    op.create_check_constraint(
        'ck_execucoes_automacao_automacao', 'execucoes_automacao', f'automacao IN ({AUTOMACOES_DEPOIS})'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM execucoes_automacao WHERE automacao = 'aviso_pontos'")
    op.drop_constraint('ck_execucoes_automacao_automacao', 'execucoes_automacao', type_='check')
    op.create_check_constraint(
        'ck_execucoes_automacao_automacao', 'execucoes_automacao', f'automacao IN ({AUTOMACOES_ANTES})'
    )
    op.drop_index(op.f('ix_avisos_pontos_enviado_em'), table_name='avisos_pontos')
    op.drop_index(op.f('ix_avisos_pontos_cliente_id'), table_name='avisos_pontos')
    op.drop_table('avisos_pontos')
