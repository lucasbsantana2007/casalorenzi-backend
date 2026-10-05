"""schema inicial

Revision ID: 8cb6cc86baf2
Revises: 
Create Date: 2026-10-05 16:39:25.084656

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8cb6cc86baf2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cria todas as tabelas da plataforma."""
    op.create_table('categorias',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=80), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('nome')
    )
    op.create_table('lojas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('cidade', sa.String(length=120), nullable=False),
    sa.Column('uf', sa.String(length=2), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('tipos_solicitacao',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=120), nullable=False),
    sa.Column('categoria', sa.String(length=60), nullable=False),
    sa.Column('descricao', sa.String(length=255), nullable=False),
    sa.Column('exige_venda', sa.Boolean(), nullable=False),
    sa.Column('conta_pos_venda', sa.String(length=20), nullable=True),
    sa.Column('ordem_exibicao', sa.Integer(), nullable=False),
    sa.Column('ativo', sa.Boolean(), server_default='true', nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('produtos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=160), nullable=False),
    sa.Column('categoria_id', sa.Integer(), nullable=False),
    sa.Column('preco_base', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('genero', sa.String(length=20), nullable=True),
    sa.Column('estacao', sa.String(length=20), nullable=True),
    sa.Column('ativo', sa.Boolean(), server_default='true', nullable=False),
    sa.ForeignKeyConstraint(['categoria_id'], ['categorias.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('usuarios',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('senha_hash', sa.String(length=255), nullable=False),
    sa.Column('papel', sa.String(length=20), nullable=False),
    sa.Column('ativo', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('loja_id', sa.Integer(), nullable=True),
    sa.Column('telefone', sa.String(length=30), nullable=True),
    sa.Column('cliente_desde', sa.Date(), nullable=True),
    sa.Column('loja_preferida_id', sa.Integer(), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("papel IN ('ADMINISTRADOR', 'LOJISTA', 'OPERADOR', 'CLIENTE')", name='ck_usuarios_papel'),
    sa.ForeignKeyConstraint(['loja_id'], ['lojas.id'], ),
    sa.ForeignKeyConstraint(['loja_preferida_id'], ['lojas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usuarios_email'), 'usuarios', ['email'], unique=True)
    op.create_table('pedidos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.String(length=30), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('loja_id', sa.Integer(), nullable=False),
    sa.Column('canal', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('codigo_rastreio', sa.String(length=40), nullable=True),
    sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("canal IN ('Loja física', 'E-commerce')", name='ck_pedidos_canal'),
    sa.CheckConstraint("status IN ('PROCESSANDO', 'ENVIADO', 'ENTREGUE', 'CANCELADO')", name='ck_pedidos_status'),
    sa.ForeignKeyConstraint(['cliente_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['loja_id'], ['lojas.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('numero')
    )
    op.create_index(op.f('ix_pedidos_cliente_id'), 'pedidos', ['cliente_id'], unique=False)
    op.create_index(op.f('ix_pedidos_criado_em'), 'pedidos', ['criado_em'], unique=False)
    op.create_table('variacoes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('produto_id', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(length=40), nullable=False),
    sa.Column('tamanho', sa.String(length=20), nullable=False),
    sa.Column('cor', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['produto_id'], ['produtos.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sku')
    )
    op.create_index(op.f('ix_variacoes_produto_id'), 'variacoes', ['produto_id'], unique=False)
    op.create_table('atendimentos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('protocolo', sa.String(length=20), nullable=False),
    sa.Column('solicitante_id', sa.Integer(), nullable=False),
    sa.Column('responsavel_id', sa.Integer(), nullable=True),
    sa.Column('tipo_solicitacao_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('pedido_id', sa.Integer(), nullable=True),
    sa.Column('loja_id', sa.Integer(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ABERTO', 'EM_ANDAMENTO', 'AGUARDANDO_CLIENTE', 'CONCLUIDO')", name='ck_atendimentos_status'),
    sa.ForeignKeyConstraint(['loja_id'], ['lojas.id'], ),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.ForeignKeyConstraint(['responsavel_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['solicitante_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['tipo_solicitacao_id'], ['tipos_solicitacao.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('protocolo')
    )
    op.create_index(op.f('ix_atendimentos_solicitante_id'), 'atendimentos', ['solicitante_id'], unique=False)
    op.create_table('estoques',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('loja_id', sa.Integer(), nullable=False),
    sa.Column('variacao_id', sa.Integer(), nullable=False),
    sa.Column('quantidade', sa.Integer(), nullable=False),
    sa.Column('quantidade_min', sa.Integer(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['loja_id'], ['lojas.id'], ),
    sa.ForeignKeyConstraint(['variacao_id'], ['variacoes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('loja_id', 'variacao_id', name='uq_estoques_loja_variacao')
    )
    op.create_index(op.f('ix_estoques_loja_id'), 'estoques', ['loja_id'], unique=False)
    op.create_index(op.f('ix_estoques_variacao_id'), 'estoques', ['variacao_id'], unique=False)
    op.create_table('itens_pedido',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pedido_id', sa.Integer(), nullable=False),
    sa.Column('variacao_id', sa.Integer(), nullable=False),
    sa.Column('quantidade', sa.Integer(), nullable=False),
    sa.Column('preco_unitario', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.ForeignKeyConstraint(['variacao_id'], ['variacoes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_itens_pedido_pedido_id'), 'itens_pedido', ['pedido_id'], unique=False)
    op.create_table('transferencias',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=20), nullable=False),
    sa.Column('variacao_id', sa.Integer(), nullable=False),
    sa.Column('loja_origem_id', sa.Integer(), nullable=False),
    sa.Column('loja_destino_id', sa.Integer(), nullable=False),
    sa.Column('quantidade', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('solicitante_id', sa.Integer(), nullable=True),
    sa.Column('responsavel_id', sa.Integer(), nullable=True),
    sa.Column('observacao', sa.Text(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('enviado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recebido_em', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('SOLICITADA', 'EM_TRANSITO', 'CONCLUIDA', 'CANCELADA')", name='ck_transferencias_status'),
    sa.ForeignKeyConstraint(['loja_destino_id'], ['lojas.id'], ),
    sa.ForeignKeyConstraint(['loja_origem_id'], ['lojas.id'], ),
    sa.ForeignKeyConstraint(['responsavel_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['solicitante_id'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['variacao_id'], ['variacoes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('codigo')
    )
    op.create_table('mensagens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('atendimento_id', sa.Integer(), nullable=False),
    sa.Column('autor_id', sa.Integer(), nullable=True),
    sa.Column('autor_tipo', sa.String(length=20), nullable=False),
    sa.Column('conteudo', sa.Text(), nullable=False),
    sa.Column('enviado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("autor_tipo IN ('CLIENTE', 'ATENDENTE', 'SISTEMA')", name='ck_mensagens_autor_tipo'),
    sa.ForeignKeyConstraint(['atendimento_id'], ['atendimentos.id'], ),
    sa.ForeignKeyConstraint(['autor_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mensagens_atendimento_id'), 'mensagens', ['atendimento_id'], unique=False)
    op.create_table('movimentacoes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('estoque_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=30), nullable=False),
    sa.Column('quantidade', sa.Integer(), nullable=False),
    sa.Column('origem', sa.String(length=255), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('transferencia_id', sa.Integer(), nullable=True),
    sa.Column('saldo_resultante', sa.Integer(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("tipo IN ('ENTRADA', 'VENDA', 'DEVOLUCAO', 'AJUSTE', 'TRANSFERENCIA_SAIDA', 'TRANSFERENCIA_ENTRADA')", name='ck_movimentacoes_tipo'),
    sa.ForeignKeyConstraint(['estoque_id'], ['estoques.id'], ),
    sa.ForeignKeyConstraint(['transferencia_id'], ['transferencias.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_movimentacoes_criado_em'), 'movimentacoes', ['criado_em'], unique=False)
    op.create_index(op.f('ix_movimentacoes_estoque_id'), 'movimentacoes', ['estoque_id'], unique=False)


def downgrade() -> None:
    """Remove todas as tabelas."""
    op.drop_index(op.f('ix_movimentacoes_estoque_id'), table_name='movimentacoes')
    op.drop_index(op.f('ix_movimentacoes_criado_em'), table_name='movimentacoes')
    op.drop_table('movimentacoes')
    op.drop_index(op.f('ix_mensagens_atendimento_id'), table_name='mensagens')
    op.drop_table('mensagens')
    op.drop_table('transferencias')
    op.drop_index(op.f('ix_itens_pedido_pedido_id'), table_name='itens_pedido')
    op.drop_table('itens_pedido')
    op.drop_index(op.f('ix_estoques_variacao_id'), table_name='estoques')
    op.drop_index(op.f('ix_estoques_loja_id'), table_name='estoques')
    op.drop_table('estoques')
    op.drop_index(op.f('ix_atendimentos_solicitante_id'), table_name='atendimentos')
    op.drop_table('atendimentos')
    op.drop_index(op.f('ix_variacoes_produto_id'), table_name='variacoes')
    op.drop_table('variacoes')
    op.drop_index(op.f('ix_pedidos_criado_em'), table_name='pedidos')
    op.drop_index(op.f('ix_pedidos_cliente_id'), table_name='pedidos')
    op.drop_table('pedidos')
    op.drop_index(op.f('ix_usuarios_email'), table_name='usuarios')
    op.drop_table('usuarios')
    op.drop_table('produtos')
    op.drop_table('tipos_solicitacao')
    op.drop_table('lojas')
    op.drop_table('categorias')
