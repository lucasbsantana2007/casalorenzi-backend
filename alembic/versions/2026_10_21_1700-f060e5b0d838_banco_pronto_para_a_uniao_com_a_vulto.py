"""banco pronto para a união com a Vulto

Prepara o banco para receber os dados da Vulto (data/vulto_corrigido.db e as tabelas *_padronizadas
do data/vulto.db, no repositório copy.vulto-legado-back). Não migra nenhum dado da Vulto: só muda a
estrutura. Tudo que já existe é da Casa Lorenzi e continua funcionando igual.

- Marca: lojas, produtos e atendimentos ganham `marca` (LORENZI | VULTO; o que existe vira LORENZI).
  Lojas ganham `tipo` (LOJA | CD): o CD Cajamar é um local de estoque, não atende o público.
- Catálogo: tabela `fornecedores`; produtos com código do modelo, coleção e fornecedor; variações com
  EAN, código do CD, preço próprio do SKU, situação no catálogo e a marca de custo estimado.
- Clientes: e-mail deixa de ser obrigatório e único (há famílias com o mesmo e-mail na Vulto);
  consentimento de marketing, canal de cadastro, "atualizar cadastro no próximo login" e observação.
- Vendas: canal App; pedido sem cliente identificado; tipo VENDA | TROCA; desconto (total = subtotal −
  desconto + frete, conferido pelo banco); status de origem, vendedor e observação. Pagamento com forma
  NAO_INFORMADO e status CHARGEBACK. Itens sempre com quantidade positiva.
- Devoluções: guardam a peça (variacao_id, preenchida a partir do item nas devoluções que já existem);
  podem não ter pedido nem item (as da Vulto que não citam a venda original) nem usuário.
- Estoque: nunca negativo; movimentações SALDO_INICIAL, INVENTARIO e AVARIA, com pedido, nota fiscal,
  custo unitário e a marca de quantidade estimada.
- Atendimento: canal (SITE, WHATSAPP, INSTAGRAM, EMAIL), contato quando não há cliente, pedido citado,
  loja opcional (SAC central) e o nome de quem escreveu a mensagem fora da plataforma.
- Novas tabelas: movimentos_pontos (extrato do Vulto+), decisoes_migracao (registro de decisões) e
  de_para (origem de cada registro migrado). Não há tabela de pendências: as pendências das planilhas
  da Vulto viraram decisões (docs/registro_decisoes_uniao.md).

Os valores permitidos ficam escritos aqui (e não importados de src/entities) para esta migração dar
sempre o mesmo resultado, mesmo que as listas mudem depois.

O downgrade só funciona antes de os dados da Vulto entrarem (com eles, há pedidos sem cliente,
e-mails repetidos etc., que a estrutura antiga não aceita).

Revision ID: f060e5b0d838
Revises: e685fb1136f9
Create Date: 2026-10-21 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f060e5b0d838"
down_revision: str | Sequence[str] | None = "e685fb1136f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    return f"{coluna} IN ({', '.join(repr(v) for v in valores)})"


MARCAS = ("LORENZI", "VULTO")
TIPOS_LOJA = ("LOJA", "CD")
CANAIS_ANTIGOS = ("Loja física", "E-commerce")
CANAIS = ("Loja física", "E-commerce", "App")
TIPOS_PEDIDO = ("VENDA", "TROCA")
METODOS_ANTIGOS = ("PIX", "CARTAO", "DINHEIRO", "DEBITO")
METODOS = (*METODOS_ANTIGOS, "NAO_INFORMADO")
STATUS_PAGAMENTO_ANTIGOS = ("APROVADO", "ESTORNADO", "PENDENTE")
STATUS_PAGAMENTO = (*STATUS_PAGAMENTO_ANTIGOS, "CHARGEBACK")
TIPOS_MOV_ANTIGOS = ("ENTRADA", "VENDA", "DEVOLUCAO", "AJUSTE", "TRANSFERENCIA_SAIDA", "TRANSFERENCIA_ENTRADA")
TIPOS_MOV = (*TIPOS_MOV_ANTIGOS, "SALDO_INICIAL", "INVENTARIO", "AVARIA")
STATUS_VARIACAO = ("ATIVO", "DESCONTINUADO", "FORA_DO_CATALOGO", "SO_HISTORICO")
CANAIS_ATENDIMENTO = ("SITE", "WHATSAPP", "INSTAGRAM", "EMAIL")
TIPOS_PONTOS = ("SALDO_INICIAL", "CREDITO", "RESGATE", "ESTORNO", "AJUSTE", "VENCIMENTO")
AREAS = ("CATALOGO", "CLIENTES", "FIDELIDADE", "VENDAS", "ESTOQUE", "ATENDIMENTO", "GERAL")
TIPOS_DECISAO = ("AUTOMATICO", "PADRAO_ASSUMIDO", "NEGOCIO")
SITUACOES_DECISAO = ("APLICADA", "A_DECIDIR")

SINAL_PONTOS = (
    "quantidade <> 0 AND (tipo NOT IN ('SALDO_INICIAL', 'CREDITO') OR quantidade > 0) "
    "AND (tipo NOT IN ('RESGATE', 'ESTORNO', 'VENCIMENTO') OR quantidade < 0)"
)


def _trocar_check(tabela: str, nome: str, condicao: str) -> None:
    op.drop_constraint(nome, tabela, type_="check")
    op.create_check_constraint(nome, tabela, condicao)


def upgrade() -> None:
    # ---------- Lojas ----------
    op.add_column("lojas", sa.Column("marca", sa.String(length=10), server_default="LORENZI", nullable=False))
    op.add_column("lojas", sa.Column("tipo", sa.String(length=10), server_default="LOJA", nullable=False))
    op.create_check_constraint("ck_lojas_marca", "lojas", _em("marca", MARCAS))
    op.create_check_constraint("ck_lojas_tipo", "lojas", _em("tipo", TIPOS_LOJA))
    op.create_index(op.f("ix_lojas_marca"), "lojas", ["marca"], unique=False)

    # ---------- Catálogo ----------
    op.create_table(
        "fornecedores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome", name="fornecedores_nome_key"),
    )

    op.add_column("produtos", sa.Column("marca", sa.String(length=10), server_default="LORENZI", nullable=False))
    op.add_column("produtos", sa.Column("codigo_modelo", sa.String(length=20), nullable=True))
    op.add_column("produtos", sa.Column("colecao", sa.String(length=40), nullable=True))
    op.add_column("produtos", sa.Column("fornecedor_id", sa.Integer(), nullable=True))
    op.add_column("produtos", sa.Column("fornecedor_estimado", sa.Boolean(), server_default="false", nullable=False))
    op.create_foreign_key("produtos_fornecedor_id_fkey", "produtos", "fornecedores", ["fornecedor_id"], ["id"])
    op.create_check_constraint("ck_produtos_marca", "produtos", _em("marca", MARCAS))
    op.create_index(op.f("ix_produtos_marca"), "produtos", ["marca"], unique=False)
    op.create_index(op.f("ix_produtos_codigo_modelo"), "produtos", ["codigo_modelo"], unique=False)

    op.add_column("variacoes", sa.Column("custo_estimado", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("variacoes", sa.Column("preco", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("variacoes", sa.Column("ean", sa.String(length=13), nullable=True))
    op.add_column("variacoes", sa.Column("codigo_cd", sa.String(length=20), nullable=True))
    op.add_column("variacoes", sa.Column("status", sa.String(length=20), server_default="ATIVO", nullable=False))
    op.add_column("variacoes", sa.Column("observacao", sa.Text(), nullable=True))
    op.create_unique_constraint("variacoes_ean_key", "variacoes", ["ean"])
    op.create_unique_constraint("variacoes_codigo_cd_key", "variacoes", ["codigo_cd"])
    op.create_check_constraint("ck_variacoes_preco", "variacoes", "preco IS NULL OR preco >= 0")
    op.create_check_constraint("ck_variacoes_ean", "variacoes", "ean IS NULL OR ean ~ '^[0-9]{13}$'")
    op.create_check_constraint("ck_variacoes_status", "variacoes", _em("status", STATUS_VARIACAO))

    # ---------- Clientes ----------
    op.add_column("clientes", sa.Column("canal_cadastro", sa.String(length=20), nullable=True))
    op.add_column("clientes", sa.Column("aceita_marketing", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("clientes", sa.Column("atualizar_cadastro", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("clientes", sa.Column("observacao", sa.Text(), nullable=True))
    op.alter_column("clientes", "email", existing_type=sa.String(length=255), nullable=True)
    op.drop_index(op.f("ix_clientes_email"), table_name="clientes")
    op.create_index(op.f("ix_clientes_email"), "clientes", ["email"], unique=False)
    op.create_check_constraint(
        "ck_clientes_identificacao", "clientes", "excluido_em IS NOT NULL OR cpf IS NOT NULL OR email IS NOT NULL"
    )
    op.create_check_constraint("ck_clientes_canal_cadastro", "clientes", _em("canal_cadastro", CANAIS))

    # ---------- Vendas ----------
    op.add_column("pedidos", sa.Column("tipo", sa.String(length=10), server_default="VENDA", nullable=False))
    op.add_column("pedidos", sa.Column("status_origem", sa.String(length=40), nullable=True))
    op.add_column("pedidos", sa.Column("desconto", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False))
    op.add_column("pedidos", sa.Column("vendedor_nome", sa.String(length=120), nullable=True))
    op.add_column("pedidos", sa.Column("cliente_contato", sa.String(length=255), nullable=True))
    op.add_column("pedidos", sa.Column("observacao", sa.Text(), nullable=True))
    op.alter_column("pedidos", "cliente_id", existing_type=sa.Integer(), nullable=True)
    _trocar_check("pedidos", "ck_pedidos_canal", _em("canal", CANAIS))
    op.create_check_constraint("ck_pedidos_tipo", "pedidos", _em("tipo", TIPOS_PEDIDO))
    op.create_check_constraint("ck_pedidos_desconto", "pedidos", "desconto >= 0 AND desconto <= subtotal")
    op.create_check_constraint("ck_pedidos_total", "pedidos", "total = subtotal - desconto + COALESCE(frete_valor, 0)")

    op.create_check_constraint("ck_itens_pedido_quantidade", "itens_pedido", "quantidade > 0")
    op.create_check_constraint("ck_itens_pedido_preco", "itens_pedido", "preco_unitario >= 0")

    _trocar_check("pagamentos", "ck_pagamentos_metodo", _em("metodo", METODOS))
    _trocar_check("pagamentos", "ck_pagamentos_status", _em("status", STATUS_PAGAMENTO))

    # ---------- Devoluções ----------
    op.add_column("devolucoes", sa.Column("variacao_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE devolucoes d SET variacao_id = i.variacao_id FROM itens_pedido i WHERE i.id = d.item_pedido_id"
    )
    op.alter_column("devolucoes", "variacao_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key("devolucoes_variacao_id_fkey", "devolucoes", "variacoes", ["variacao_id"], ["id"])
    op.create_index(op.f("ix_devolucoes_variacao_id"), "devolucoes", ["variacao_id"], unique=False)
    op.alter_column("devolucoes", "item_pedido_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("devolucoes", "pedido_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("devolucoes", "usuario_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "ck_devolucoes_item_do_pedido", "devolucoes", "item_pedido_id IS NULL OR pedido_id IS NOT NULL"
    )

    # ---------- Estoque ----------
    op.create_check_constraint("ck_estoques_quantidade", "estoques", "quantidade >= 0 AND quantidade_min >= 0")

    op.add_column("movimentacoes", sa.Column("pedido_id", sa.Integer(), nullable=True))
    op.add_column("movimentacoes", sa.Column("nota_fiscal", sa.String(length=40), nullable=True))
    op.add_column("movimentacoes", sa.Column("custo_unitario", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("movimentacoes", sa.Column("estimado", sa.Boolean(), server_default="false", nullable=False))
    op.create_foreign_key("movimentacoes_pedido_id_fkey", "movimentacoes", "pedidos", ["pedido_id"], ["id"])
    op.create_index(op.f("ix_movimentacoes_pedido_id"), "movimentacoes", ["pedido_id"], unique=False)
    # Envios e devoluções de pedidos feitos pela plataforma (o texto da origem traz o número do pedido)
    op.execute(
        """
        UPDATE movimentacoes m SET pedido_id = p.id
        FROM pedidos p
        WHERE m.origem = 'Pedido ' || p.numero || ' (e-commerce)'
           OR m.origem = 'Devolução do pedido ' || p.numero
        """
    )
    _trocar_check("movimentacoes", "ck_movimentacoes_tipo", _em("tipo", TIPOS_MOV))
    op.create_check_constraint("ck_movimentacoes_saldo", "movimentacoes", "saldo_resultante >= 0")
    op.create_check_constraint("ck_movimentacoes_custo", "movimentacoes", "custo_unitario IS NULL OR custo_unitario >= 0")

    # ---------- Atendimento ----------
    op.add_column("atendimentos", sa.Column("marca", sa.String(length=10), server_default="LORENZI", nullable=False))
    op.add_column("atendimentos", sa.Column("canal", sa.String(length=20), server_default="SITE", nullable=False))
    op.add_column("atendimentos", sa.Column("contato", sa.String(length=255), nullable=True))
    op.add_column("atendimentos", sa.Column("contato_nome", sa.String(length=120), nullable=True))
    op.add_column("atendimentos", sa.Column("pedido_citado", sa.String(length=40), nullable=True))
    op.alter_column("atendimentos", "cliente_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("atendimentos", "loja_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint("ck_atendimentos_canal", "atendimentos", _em("canal", CANAIS_ATENDIMENTO))
    op.create_check_constraint("ck_atendimentos_marca", "atendimentos", _em("marca", MARCAS))
    op.create_check_constraint(
        "ck_atendimentos_cliente_ou_contato", "atendimentos", "cliente_id IS NOT NULL OR contato IS NOT NULL"
    )
    op.create_index(op.f("ix_atendimentos_marca"), "atendimentos", ["marca"], unique=False)
    op.create_index(op.f("ix_atendimentos_contato"), "atendimentos", ["contato"], unique=False)

    op.add_column("mensagens", sa.Column("autor_nome", sa.String(length=120), nullable=True))

    # ---------- Vulto+ ----------
    op.create_table(
        "movimentos_pontos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("saldo_resultante", sa.Integer(), nullable=False),
        sa.Column("vence_em", sa.Date(), nullable=True),
        sa.Column("pedido_id", sa.Integer(), nullable=True),
        sa.Column("loja_id", sa.Integer(), nullable=True),
        sa.Column("valor_desconto", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("obs", sa.Text(), server_default="", nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_em("tipo", TIPOS_PONTOS), name="ck_movimentos_pontos_tipo"),
        sa.CheckConstraint(SINAL_PONTOS, name="ck_movimentos_pontos_sinal"),
        sa.CheckConstraint("saldo_resultante >= 0", name="ck_movimentos_pontos_saldo"),
        sa.CheckConstraint("valor_desconto IS NULL OR valor_desconto >= 0", name="ck_movimentos_pontos_valor"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], name="movimentos_pontos_cliente_id_fkey"),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"], name="movimentos_pontos_pedido_id_fkey"),
        sa.ForeignKeyConstraint(["loja_id"], ["lojas.id"], name="movimentos_pontos_loja_id_fkey"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_movimentos_pontos_cliente_data", "movimentos_pontos", ["cliente_id", "criado_em", "id"], unique=False)
    op.create_index(op.f("ix_movimentos_pontos_criado_em"), "movimentos_pontos", ["criado_em"], unique=False)
    op.create_index(op.f("ix_movimentos_pontos_pedido_id"), "movimentos_pontos", ["pedido_id"], unique=False)

    # ---------- Migração: registro de decisões e de-para ----------
    op.create_table(
        "decisoes_migracao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(length=20), nullable=False),
        sa.Column("o_que_encontramos", sa.Text(), nullable=False),
        sa.Column("onde", sa.Text(), nullable=False),
        sa.Column("quantos_registros", sa.Text(), nullable=False),
        sa.Column("o_que_decidimos", sa.Text(), nullable=False),
        sa.Column("por_que", sa.Text(), nullable=False),
        sa.Column("impacto", sa.Text(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("situacao", sa.String(length=20), server_default="APLICADA", nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_em("area", AREAS), name="ck_decisoes_migracao_area"),
        sa.CheckConstraint(_em("tipo", TIPOS_DECISAO), name="ck_decisoes_migracao_tipo"),
        sa.CheckConstraint(_em("situacao", SITUACOES_DECISAO), name="ck_decisoes_migracao_situacao"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("numero", name="decisoes_migracao_numero_key"),
    )
    op.create_table(
        "de_para",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("origem", sa.String(length=120), nullable=False),
        sa.Column("id_origem", sa.String(length=120), nullable=False),
        sa.Column("tabela_destino", sa.String(length=40), nullable=False),
        sa.Column("id_destino", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("origem", "id_origem", "tabela_destino", name="uq_de_para_origem"),
    )
    op.create_index("ix_de_para_destino", "de_para", ["tabela_destino", "id_destino"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_de_para_destino", table_name="de_para")
    op.drop_table("de_para")
    op.drop_table("decisoes_migracao")

    op.drop_index(op.f("ix_movimentos_pontos_pedido_id"), table_name="movimentos_pontos")
    op.drop_index(op.f("ix_movimentos_pontos_criado_em"), table_name="movimentos_pontos")
    op.drop_index("ix_movimentos_pontos_cliente_data", table_name="movimentos_pontos")
    op.drop_table("movimentos_pontos")

    op.drop_column("mensagens", "autor_nome")

    op.drop_index(op.f("ix_atendimentos_contato"), table_name="atendimentos")
    op.drop_index(op.f("ix_atendimentos_marca"), table_name="atendimentos")
    op.drop_constraint("ck_atendimentos_cliente_ou_contato", "atendimentos", type_="check")
    op.drop_constraint("ck_atendimentos_marca", "atendimentos", type_="check")
    op.drop_constraint("ck_atendimentos_canal", "atendimentos", type_="check")
    op.alter_column("atendimentos", "loja_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("atendimentos", "cliente_id", existing_type=sa.Integer(), nullable=False)
    for coluna in ("pedido_citado", "contato_nome", "contato", "canal", "marca"):
        op.drop_column("atendimentos", coluna)

    op.drop_constraint("ck_movimentacoes_custo", "movimentacoes", type_="check")
    op.drop_constraint("ck_movimentacoes_saldo", "movimentacoes", type_="check")
    _trocar_check("movimentacoes", "ck_movimentacoes_tipo", _em("tipo", TIPOS_MOV_ANTIGOS))
    op.drop_index(op.f("ix_movimentacoes_pedido_id"), table_name="movimentacoes")
    op.drop_constraint("movimentacoes_pedido_id_fkey", "movimentacoes", type_="foreignkey")
    for coluna in ("estimado", "custo_unitario", "nota_fiscal", "pedido_id"):
        op.drop_column("movimentacoes", coluna)
    op.drop_constraint("ck_estoques_quantidade", "estoques", type_="check")

    op.drop_constraint("ck_devolucoes_item_do_pedido", "devolucoes", type_="check")
    op.alter_column("devolucoes", "usuario_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("devolucoes", "pedido_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("devolucoes", "item_pedido_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index(op.f("ix_devolucoes_variacao_id"), table_name="devolucoes")
    op.drop_constraint("devolucoes_variacao_id_fkey", "devolucoes", type_="foreignkey")
    op.drop_column("devolucoes", "variacao_id")

    _trocar_check("pagamentos", "ck_pagamentos_status", _em("status", STATUS_PAGAMENTO_ANTIGOS))
    _trocar_check("pagamentos", "ck_pagamentos_metodo", _em("metodo", METODOS_ANTIGOS))
    op.drop_constraint("ck_itens_pedido_preco", "itens_pedido", type_="check")
    op.drop_constraint("ck_itens_pedido_quantidade", "itens_pedido", type_="check")

    op.drop_constraint("ck_pedidos_total", "pedidos", type_="check")
    op.drop_constraint("ck_pedidos_desconto", "pedidos", type_="check")
    op.drop_constraint("ck_pedidos_tipo", "pedidos", type_="check")
    _trocar_check("pedidos", "ck_pedidos_canal", _em("canal", CANAIS_ANTIGOS))
    op.alter_column("pedidos", "cliente_id", existing_type=sa.Integer(), nullable=False)
    for coluna in ("observacao", "cliente_contato", "vendedor_nome", "desconto", "status_origem", "tipo"):
        op.drop_column("pedidos", coluna)

    op.drop_constraint("ck_clientes_canal_cadastro", "clientes", type_="check")
    op.drop_constraint("ck_clientes_identificacao", "clientes", type_="check")
    op.drop_index(op.f("ix_clientes_email"), table_name="clientes")
    op.create_index(op.f("ix_clientes_email"), "clientes", ["email"], unique=True)
    op.alter_column("clientes", "email", existing_type=sa.String(length=255), nullable=False)
    for coluna in ("observacao", "atualizar_cadastro", "aceita_marketing", "canal_cadastro"):
        op.drop_column("clientes", coluna)

    op.drop_constraint("ck_variacoes_status", "variacoes", type_="check")
    op.drop_constraint("ck_variacoes_ean", "variacoes", type_="check")
    op.drop_constraint("ck_variacoes_preco", "variacoes", type_="check")
    op.drop_constraint("variacoes_codigo_cd_key", "variacoes", type_="unique")
    op.drop_constraint("variacoes_ean_key", "variacoes", type_="unique")
    for coluna in ("observacao", "status", "codigo_cd", "ean", "preco", "custo_estimado"):
        op.drop_column("variacoes", coluna)

    op.drop_index(op.f("ix_produtos_codigo_modelo"), table_name="produtos")
    op.drop_index(op.f("ix_produtos_marca"), table_name="produtos")
    op.drop_constraint("ck_produtos_marca", "produtos", type_="check")
    op.drop_constraint("produtos_fornecedor_id_fkey", "produtos", type_="foreignkey")
    for coluna in ("fornecedor_estimado", "fornecedor_id", "colecao", "codigo_modelo", "marca"):
        op.drop_column("produtos", coluna)
    op.drop_table("fornecedores")

    op.drop_index(op.f("ix_lojas_marca"), table_name="lojas")
    op.drop_constraint("ck_lojas_tipo", "lojas", type_="check")
    op.drop_constraint("ck_lojas_marca", "lojas", type_="check")
    op.drop_column("lojas", "tipo")
    op.drop_column("lojas", "marca")
