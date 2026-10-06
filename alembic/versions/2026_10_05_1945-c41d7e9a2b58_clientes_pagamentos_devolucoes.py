"""clientes separados da equipe, pagamentos, devolucoes, anexos e tokens de PIN

- Cliente deixa de ser usuário: os usuários com papel CLIENTE viram linhas de `clientes`
  (com os MESMOS ids) e pedidos/atendimentos passam a apontar para `clientes`.
  Usuários da equipe que aparecem como comprador/solicitante também ganham uma cópia em
  `clientes` (mesmo id), para nenhuma FK ficar órfã; eles continuam na equipe.
- 'CLIENTE' sai do check de papel; telefone/cliente_desde/loja_preferida_id saem de `usuarios`.
- Mensagens do cliente ficam com autor_id nulo (autor_id só aponta para a equipe).
- Pedidos ganham subtotal (= total nos pedidos antigos), frete e endereço de entrega.
- Produtos ganham descrição, composição e cuidados.
- Novas tabelas: pagamentos, devolucoes, anexos, tokens_pin.
- Cada pedido existente ganha um pagamento (valor = total; método pelo canal:
  E-commerce → CARTAO, Loja física → DEBITO). Status APROVADO, exceto pedidos CANCELADO,
  cujo pagamento nasce ESTORNADO (o dinheiro já foi devolvido).

O PIN dos clientes migrados fica nulo: a senha antiga não vira PIN. O cliente cria o PIN
pelo fluxo "esqueci o PIN" (tokens_pin) ou na próxima compra.

Revision ID: c41d7e9a2b58
Revises: 8cb6cc86baf2
Create Date: 2026-10-05 19:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c41d7e9a2b58'
down_revision: Union[str, Sequence[str], None] = '8cb6cc86baf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USUARIOS_CLIENTE = "SELECT id FROM usuarios WHERE papel = 'CLIENTE'"


def _ajustar_sequencia(tabela: str) -> None:
    """Depois de inserir ids explícitos, o próximo id gerado precisa vir depois deles."""
    op.execute(
        f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
        f"COALESCE((SELECT MAX(id) FROM {tabela}), 0) + 1, false)"
    )


def upgrade() -> None:
    # ---------- clientes ----------
    op.create_table('clientes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('telefone', sa.String(length=30), nullable=True),
    sa.Column('pin_hash', sa.String(length=255), nullable=True),
    sa.Column('tentativas_pin', sa.Integer(), server_default='0', nullable=False),
    sa.Column('bloqueado_ate', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cliente_desde', sa.Date(), server_default=sa.text('CURRENT_DATE'), nullable=False),
    sa.Column('loja_preferida_id', sa.Integer(), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('email = lower(email)', name='ck_clientes_email_minusculo'),
    sa.CheckConstraint('tentativas_pin >= 0', name='ck_clientes_tentativas_pin'),
    sa.ForeignKeyConstraint(['loja_preferida_id'], ['lojas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clientes_email'), 'clientes', ['email'], unique=True)

    op.execute(f"""
        INSERT INTO clientes (id, nome, email, telefone, pin_hash, tentativas_pin, bloqueado_ate,
                              cliente_desde, loja_preferida_id, criado_em)
        SELECT u.id, u.nome, lower(trim(u.email)), u.telefone, NULL, 0, NULL,
               COALESCE(u.cliente_desde, (u.criado_em AT TIME ZONE 'America/Sao_Paulo')::date),
               u.loja_preferida_id, u.criado_em
        FROM usuarios u
        WHERE u.id IN ({USUARIOS_CLIENTE})
           OR u.id IN (SELECT cliente_id FROM pedidos)
           OR u.id IN (SELECT solicitante_id FROM atendimentos)
    """)
    _ajustar_sequencia('clientes')

    # ---------- pedidos: cliente, subtotal, frete e entrega ----------
    op.drop_constraint('pedidos_cliente_id_fkey', 'pedidos', type_='foreignkey')
    op.create_foreign_key('pedidos_cliente_id_fkey', 'pedidos', 'clientes', ['cliente_id'], ['id'])

    op.add_column('pedidos', sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=True))
    op.execute("UPDATE pedidos SET subtotal = total")
    op.alter_column('pedidos', 'subtotal', nullable=False)
    op.add_column('pedidos', sa.Column('frete_tipo', sa.String(length=20), nullable=True))
    op.add_column('pedidos', sa.Column('frete_valor', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('pedidos', sa.Column('frete_prazo_dias', sa.Integer(), nullable=True))
    op.add_column('pedidos', sa.Column('entrega_cep', sa.String(length=8), nullable=True))
    op.add_column('pedidos', sa.Column('entrega_rua', sa.String(length=160), nullable=True))
    op.add_column('pedidos', sa.Column('entrega_numero', sa.String(length=20), nullable=True))
    op.add_column('pedidos', sa.Column('entrega_complemento', sa.String(length=80), nullable=True))
    op.add_column('pedidos', sa.Column('entrega_bairro', sa.String(length=80), nullable=True))
    op.add_column('pedidos', sa.Column('entrega_cidade', sa.String(length=120), nullable=True))
    op.add_column('pedidos', sa.Column('entrega_uf', sa.String(length=2), nullable=True))
    op.create_check_constraint('ck_pedidos_frete_tipo', 'pedidos', "frete_tipo IN ('PADRAO', 'EXPRESSO')")

    # ---------- atendimentos: solicitante_id (usuarios) → cliente_id (clientes) ----------
    op.drop_constraint('atendimentos_solicitante_id_fkey', 'atendimentos', type_='foreignkey')
    op.drop_index(op.f('ix_atendimentos_solicitante_id'), table_name='atendimentos')
    op.alter_column('atendimentos', 'solicitante_id', new_column_name='cliente_id')
    op.create_index(op.f('ix_atendimentos_cliente_id'), 'atendimentos', ['cliente_id'], unique=False)
    op.create_foreign_key('atendimentos_cliente_id_fkey', 'atendimentos', 'clientes', ['cliente_id'], ['id'])

    # ---------- referências restantes a usuários CLIENTE (que serão apagados) ----------
    op.execute(f"UPDATE mensagens SET autor_id = NULL WHERE autor_tipo = 'CLIENTE' OR autor_id IN ({USUARIOS_CLIENTE})")
    op.create_check_constraint('ck_mensagens_autor_cliente', 'mensagens', "autor_tipo <> 'CLIENTE' OR autor_id IS NULL")
    op.execute(f"UPDATE atendimentos SET responsavel_id = NULL WHERE responsavel_id IN ({USUARIOS_CLIENTE})")
    op.execute(f"UPDATE movimentacoes SET usuario_id = NULL WHERE usuario_id IN ({USUARIOS_CLIENTE})")
    op.execute(f"UPDATE transferencias SET solicitante_id = NULL WHERE solicitante_id IN ({USUARIOS_CLIENTE})")
    op.execute(f"UPDATE transferencias SET responsavel_id = NULL WHERE responsavel_id IN ({USUARIOS_CLIENTE})")

    # ---------- usuarios: só a equipe ----------
    op.execute("DELETE FROM usuarios WHERE papel = 'CLIENTE'")
    op.drop_constraint('usuarios_loja_preferida_id_fkey', 'usuarios', type_='foreignkey')
    op.drop_column('usuarios', 'loja_preferida_id')
    op.drop_column('usuarios', 'cliente_desde')
    op.drop_column('usuarios', 'telefone')
    op.drop_constraint('ck_usuarios_papel', 'usuarios', type_='check')
    op.create_check_constraint('ck_usuarios_papel', 'usuarios', "papel IN ('ADMINISTRADOR', 'LOJISTA', 'OPERADOR')")

    # ---------- produtos: textos da página do produto ----------
    op.add_column('produtos', sa.Column('descricao', sa.Text(), nullable=True))
    op.add_column('produtos', sa.Column('composicao', sa.Text(), nullable=True))
    op.add_column('produtos', sa.Column('cuidados', sa.Text(), nullable=True))

    # ---------- tabelas novas ----------
    op.create_table('tokens_pin',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('expira_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('usado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )
    op.create_index(op.f('ix_tokens_pin_cliente_id'), 'tokens_pin', ['cliente_id'], unique=False)

    op.create_table('pagamentos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pedido_id', sa.Integer(), nullable=False),
    sa.Column('metodo', sa.String(length=20), nullable=False),
    sa.Column('valor', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('parcelas', sa.Integer(), server_default='1', nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("metodo IN ('PIX', 'CARTAO', 'DINHEIRO', 'DEBITO')", name='ck_pagamentos_metodo'),
    sa.CheckConstraint("status IN ('APROVADO', 'ESTORNADO', 'PENDENTE')", name='ck_pagamentos_status'),
    sa.CheckConstraint('parcelas BETWEEN 1 AND 6', name='ck_pagamentos_parcelas'),
    sa.CheckConstraint('valor >= 0', name='ck_pagamentos_valor'),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pagamentos_pedido_id'), 'pagamentos', ['pedido_id'], unique=False)

    op.create_table('devolucoes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('item_pedido_id', sa.Integer(), nullable=False),
    sa.Column('pedido_id', sa.Integer(), nullable=False),
    sa.Column('atendimento_id', sa.Integer(), nullable=True),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.Column('loja_id', sa.Integer(), nullable=False),
    sa.Column('movimentacao_id', sa.Integer(), nullable=True),
    sa.Column('quantidade', sa.Integer(), nullable=False),
    sa.Column('valor_devolvido', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('motivo', sa.Text(), nullable=False),
    sa.Column('criada_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantidade > 0', name='ck_devolucoes_quantidade'),
    sa.CheckConstraint('valor_devolvido >= 0', name='ck_devolucoes_valor'),
    sa.ForeignKeyConstraint(['atendimento_id'], ['atendimentos.id'], ),
    sa.ForeignKeyConstraint(['item_pedido_id'], ['itens_pedido.id'], ),
    sa.ForeignKeyConstraint(['loja_id'], ['lojas.id'], ),
    sa.ForeignKeyConstraint(['movimentacao_id'], ['movimentacoes.id'], ),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_devolucoes_criada_em'), 'devolucoes', ['criada_em'], unique=False)
    op.create_index(op.f('ix_devolucoes_item_pedido_id'), 'devolucoes', ['item_pedido_id'], unique=False)
    op.create_index(op.f('ix_devolucoes_loja_id'), 'devolucoes', ['loja_id'], unique=False)
    op.create_index(op.f('ix_devolucoes_pedido_id'), 'devolucoes', ['pedido_id'], unique=False)

    op.create_table('anexos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mensagem_id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('tipo', sa.String(length=30), nullable=False),
    sa.Column('tamanho', sa.Integer(), nullable=False),
    sa.Column('dados', sa.LargeBinary(), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("tipo IN ('image/jpeg', 'image/png', 'image/webp')", name='ck_anexos_tipo'),
    sa.CheckConstraint('tamanho > 0 AND tamanho <= 2097152', name='ck_anexos_tamanho'),
    sa.ForeignKeyConstraint(['mensagem_id'], ['mensagens.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mensagem_id')
    )

    # ---------- um pagamento para cada pedido existente ----------
    op.execute("""
        INSERT INTO pagamentos (pedido_id, metodo, valor, parcelas, status, criado_em, atualizado_em)
        SELECT p.id,
               CASE p.canal WHEN 'E-commerce' THEN 'CARTAO' ELSE 'DEBITO' END,
               p.total,
               1,
               CASE p.status WHEN 'CANCELADO' THEN 'ESTORNADO' ELSE 'APROVADO' END,
               p.criado_em,
               p.criado_em
        FROM pedidos p
        ORDER BY p.id
    """)


def downgrade() -> None:
    """Volta os clientes para `usuarios` (papel CLIENTE, sem senha utilizável) e apaga pagamentos,
    devoluções, anexos e tokens. PIN, tentativas e bloqueio dos clientes se perdem."""
    op.drop_table('anexos')
    op.drop_index(op.f('ix_devolucoes_pedido_id'), table_name='devolucoes')
    op.drop_index(op.f('ix_devolucoes_loja_id'), table_name='devolucoes')
    op.drop_index(op.f('ix_devolucoes_item_pedido_id'), table_name='devolucoes')
    op.drop_index(op.f('ix_devolucoes_criada_em'), table_name='devolucoes')
    op.drop_table('devolucoes')
    op.drop_index(op.f('ix_pagamentos_pedido_id'), table_name='pagamentos')
    op.drop_table('pagamentos')
    op.drop_index(op.f('ix_tokens_pin_cliente_id'), table_name='tokens_pin')
    op.drop_table('tokens_pin')

    op.drop_column('produtos', 'cuidados')
    op.drop_column('produtos', 'composicao')
    op.drop_column('produtos', 'descricao')

    # ---------- usuarios volta a aceitar CLIENTE ----------
    op.drop_constraint('ck_usuarios_papel', 'usuarios', type_='check')
    op.create_check_constraint(
        'ck_usuarios_papel', 'usuarios', "papel IN ('ADMINISTRADOR', 'LOJISTA', 'OPERADOR', 'CLIENTE')"
    )
    op.add_column('usuarios', sa.Column('telefone', sa.String(length=30), nullable=True))
    op.add_column('usuarios', sa.Column('cliente_desde', sa.Date(), nullable=True))
    op.add_column('usuarios', sa.Column('loja_preferida_id', sa.Integer(), nullable=True))
    op.create_foreign_key('usuarios_loja_preferida_id_fkey', 'usuarios', 'lojas', ['loja_preferida_id'], ['id'])

    # Cada cliente vira (ou reencontra) um usuário. Clientes criados depois do upgrade podem ter
    # id já usado por alguém da equipe: esses ganham um id novo da sequência de usuarios.
    op.execute(
        "SELECT setval(pg_get_serial_sequence('usuarios', 'id'), "
        "GREATEST((SELECT COALESCE(MAX(id), 0) FROM usuarios), (SELECT COALESCE(MAX(id), 0) FROM clientes)) + 1, false)"
    )
    op.execute("""
        CREATE TEMPORARY TABLE mapa_clientes AS
        SELECT c.id AS cliente_id,
               COALESCE(por_email.id, CASE WHEN por_id.id IS NULL THEN c.id END) AS usuario_id,
               por_email.id IS NULL AS inserir
        FROM clientes c
        LEFT JOIN usuarios por_email ON lower(por_email.email) = c.email
        LEFT JOIN usuarios por_id ON por_id.id = c.id
    """)
    op.execute(
        "UPDATE mapa_clientes SET usuario_id = nextval(pg_get_serial_sequence('usuarios', 'id')) WHERE usuario_id IS NULL"
    )
    op.execute("""
        INSERT INTO usuarios (id, nome, email, senha_hash, papel, ativo, telefone, cliente_desde, loja_preferida_id, criado_em)
        SELECT mc.usuario_id, c.nome, c.email, '!sem-senha', 'CLIENTE', true,
               c.telefone, c.cliente_desde, c.loja_preferida_id, c.criado_em
        FROM clientes c
        JOIN mapa_clientes mc ON mc.cliente_id = c.id
        WHERE mc.inserir
    """)
    _ajustar_sequencia('usuarios')

    # ---------- pedidos volta a apontar para usuarios ----------
    op.drop_constraint('pedidos_cliente_id_fkey', 'pedidos', type_='foreignkey')
    op.execute("UPDATE pedidos p SET cliente_id = mc.usuario_id FROM mapa_clientes mc WHERE p.cliente_id = mc.cliente_id")
    op.create_foreign_key('pedidos_cliente_id_fkey', 'pedidos', 'usuarios', ['cliente_id'], ['id'])
    op.drop_constraint('ck_pedidos_frete_tipo', 'pedidos', type_='check')
    op.drop_column('pedidos', 'entrega_uf')
    op.drop_column('pedidos', 'entrega_cidade')
    op.drop_column('pedidos', 'entrega_bairro')
    op.drop_column('pedidos', 'entrega_complemento')
    op.drop_column('pedidos', 'entrega_numero')
    op.drop_column('pedidos', 'entrega_rua')
    op.drop_column('pedidos', 'entrega_cep')
    op.drop_column('pedidos', 'frete_prazo_dias')
    op.drop_column('pedidos', 'frete_valor')
    op.drop_column('pedidos', 'frete_tipo')
    op.drop_column('pedidos', 'subtotal')

    # ---------- atendimentos: cliente_id → solicitante_id ----------
    op.drop_constraint('atendimentos_cliente_id_fkey', 'atendimentos', type_='foreignkey')
    op.drop_index(op.f('ix_atendimentos_cliente_id'), table_name='atendimentos')
    op.execute("UPDATE atendimentos a SET cliente_id = mc.usuario_id FROM mapa_clientes mc WHERE a.cliente_id = mc.cliente_id")
    op.alter_column('atendimentos', 'cliente_id', new_column_name='solicitante_id')
    op.create_index(op.f('ix_atendimentos_solicitante_id'), 'atendimentos', ['solicitante_id'], unique=False)
    op.create_foreign_key('atendimentos_solicitante_id_fkey', 'atendimentos', 'usuarios', ['solicitante_id'], ['id'])

    # ---------- mensagens do cliente voltam a ter autor ----------
    op.drop_constraint('ck_mensagens_autor_cliente', 'mensagens', type_='check')
    op.execute("""
        UPDATE mensagens m SET autor_id = a.solicitante_id
        FROM atendimentos a
        WHERE m.atendimento_id = a.id AND m.autor_tipo = 'CLIENTE' AND m.autor_id IS NULL
    """)

    op.execute("DROP TABLE mapa_clientes")
    op.drop_index(op.f('ix_clientes_email'), table_name='clientes')
    op.drop_table('clientes')
