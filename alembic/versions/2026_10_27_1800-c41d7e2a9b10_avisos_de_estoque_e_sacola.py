"""avisos de estoque e sacola

"Avise-me quando chegar" e lembrete de sacola abandonada (decisões 99 e 100, docs/registro_decisoes_e4.md):
- avisos_estoque: o pedido do cliente para saber quando uma peça esgotada voltar (um pendente por peça);
- sacolas: cópia da sacola do cliente logado, para o lembrete e para abrir a sacola em outro aparelho;
- execucoes_automacao passa a aceitar as automações aviso_estoque e lembrete_sacola.
Só acrescenta: nenhuma tabela ou dado existente muda. O downgrade apaga as duas tabelas e o log dessas automações.

Revision ID: c41d7e2a9b10
Revises: 5b7e1c9a3f20
Create Date: 2026-10-27 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c41d7e2a9b10'
down_revision: str | Sequence[str] | None = '5b7e1c9a3f20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTOMACOES_ANTES = (
    "'estoque_baixo', 'estoque_parado', 'sugestoes_transferencia', 'pontos_a_vencer', 'aviso_pontos', 'limpeza_conversas'"
)
AUTOMACOES_DEPOIS = (
    "'estoque_baixo', 'estoque_parado', 'sugestoes_transferencia', 'pontos_a_vencer', 'aviso_pontos', "
    "'aviso_estoque', 'lembrete_sacola', 'limpeza_conversas'"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('avisos_estoque',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('variacao_id', sa.Integer(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('avisado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('modo', sa.String(length=5), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.CheckConstraint("modo IS NULL OR modo IN ('REAL', 'TESTE')", name='ck_avisos_estoque_modo'),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['variacao_id'], ['variacoes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_avisos_estoque_cliente_id'), 'avisos_estoque', ['cliente_id'], unique=False)
    op.create_index(op.f('ix_avisos_estoque_variacao_id'), 'avisos_estoque', ['variacao_id'], unique=False)
    op.create_index(op.f('ix_avisos_estoque_avisado_em'), 'avisos_estoque', ['avisado_em'], unique=False)
    op.create_index(
        'uq_avisos_estoque_pendente', 'avisos_estoque', ['cliente_id', 'variacao_id'], unique=True,
        postgresql_where=sa.text('avisado_em IS NULL'),
    )
    op.create_table('sacolas',
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('itens', sa.JSON(), nullable=False),
    sa.Column('atualizada_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lembrete_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lembrete_modo', sa.String(length=5), nullable=True),
    sa.CheckConstraint("lembrete_modo IS NULL OR lembrete_modo IN ('REAL', 'TESTE')", name='ck_sacolas_lembrete_modo'),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('cliente_id')
    )
    op.create_index(op.f('ix_sacolas_atualizada_em'), 'sacolas', ['atualizada_em'], unique=False)
    op.drop_constraint('ck_execucoes_automacao_automacao', 'execucoes_automacao', type_='check')
    op.create_check_constraint(
        'ck_execucoes_automacao_automacao', 'execucoes_automacao', f'automacao IN ({AUTOMACOES_DEPOIS})'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM execucoes_automacao WHERE automacao IN ('aviso_estoque', 'lembrete_sacola')")
    op.drop_constraint('ck_execucoes_automacao_automacao', 'execucoes_automacao', type_='check')
    op.create_check_constraint(
        'ck_execucoes_automacao_automacao', 'execucoes_automacao', f'automacao IN ({AUTOMACOES_ANTES})'
    )
    op.drop_index(op.f('ix_sacolas_atualizada_em'), table_name='sacolas')
    op.drop_table('sacolas')
    op.drop_index('uq_avisos_estoque_pendente', table_name='avisos_estoque')
    op.drop_index(op.f('ix_avisos_estoque_avisado_em'), table_name='avisos_estoque')
    op.drop_index(op.f('ix_avisos_estoque_variacao_id'), table_name='avisos_estoque')
    op.drop_index(op.f('ix_avisos_estoque_cliente_id'), table_name='avisos_estoque')
    op.drop_table('avisos_estoque')
