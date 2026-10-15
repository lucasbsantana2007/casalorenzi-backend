"""união com a Vulto: marca, canal App, apoio da migração e Vulto+

- lojas: marca (LORENZI | VULTO) e tipo (FISICA | CD | VIRTUAL); as lojas existentes ficam LORENZI/FISICA.
- produtos: marca (as existentes ficam LORENZI) e colecao; variacoes: ean (EAN-13, único).
- pedidos: canal "App" além de "Loja física" e "E-commerce".
- clientes: e-mail opcional (clientes da Vulto com só CPF ou telefone), com pelo menos um
  identificador; consentimento de marketing (LGPD), falso para todos os clientes existentes.
- Novas: sku_alias (grafias de SKU com vigência), de_para e migracao_ocorrencias (rastreio da
  migração), contas_pontos e movimentos_pontos (Vulto+).

As lojas da Vulto não entram aqui: o pipeline (python -m src.migracao_vulto --dominio lojas) as
cadastra, porque o seed --recriar apaga todas as tabelas.

Revision ID: e0e3ab34ad9d
Revises: e685fb1136f9
Create Date: 2026-10-14 22:07:56.984538

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e0e3ab34ad9d"
down_revision: str | Sequence[str] | None = "e685fb1136f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- Marca e tipo ----------
    op.add_column("lojas", sa.Column("marca", sa.String(length=10), server_default="LORENZI", nullable=False))
    op.add_column("lojas", sa.Column("tipo", sa.String(length=10), server_default="FISICA", nullable=False))
    op.create_index(op.f("ix_lojas_marca"), "lojas", ["marca"], unique=False)
    op.create_check_constraint("ck_lojas_marca", "lojas", "marca IN ('LORENZI', 'VULTO')")
    op.create_check_constraint("ck_lojas_tipo", "lojas", "tipo IN ('FISICA', 'CD', 'VIRTUAL')")

    op.add_column("produtos", sa.Column("marca", sa.String(length=10), server_default="LORENZI", nullable=False))
    op.add_column("produtos", sa.Column("colecao", sa.String(length=40), nullable=True))
    op.create_index(op.f("ix_produtos_marca"), "produtos", ["marca"], unique=False)
    op.create_check_constraint("ck_produtos_marca", "produtos", "marca IN ('LORENZI', 'VULTO')")

    op.add_column("variacoes", sa.Column("ean", sa.String(length=13), nullable=True))
    op.create_unique_constraint("variacoes_ean_key", "variacoes", ["ean"])
    op.create_check_constraint("ck_variacoes_ean", "variacoes", "ean IS NULL OR ean ~ '^[0-9]{13}$'")

    # ---------- Canal App ----------
    op.drop_constraint("ck_pedidos_canal", "pedidos", type_="check")
    op.create_check_constraint("ck_pedidos_canal", "pedidos", "canal IN ('Loja física', 'E-commerce', 'App')")

    # ---------- Clientes: e-mail opcional e consentimento ----------
    op.alter_column("clientes", "email", existing_type=sa.VARCHAR(length=255), nullable=True)
    op.create_check_constraint(
        "ck_clientes_identificador", "clientes", "cpf IS NOT NULL OR email IS NOT NULL OR telefone IS NOT NULL"
    )
    op.add_column("clientes", sa.Column("aceita_marketing", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("clientes", sa.Column("aceita_marketing_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clientes", sa.Column("aceita_marketing_origem", sa.String(length=60), nullable=True))

    # ---------- Grafias de SKU ----------
    op.create_table(
        "sku_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("variacao_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=80), nullable=False),
        sa.Column("alias_normalizado", sa.String(length=80), nullable=False),
        sa.Column("origem", sa.String(length=120), server_default="", nullable=False),
        sa.Column("valido_de", sa.Date(), nullable=True),
        sa.Column("valido_ate", sa.Date(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "valido_de IS NULL OR valido_ate IS NULL OR valido_ate >= valido_de", name="ck_sku_alias_vigencia"
        ),
        sa.ForeignKeyConstraint(["variacao_id"], ["variacoes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "alias_normalizado", "valido_de", name="uq_sku_alias_vigencia", postgresql_nulls_not_distinct=True
        ),
    )
    op.create_index(op.f("ix_sku_alias_alias_normalizado"), "sku_alias", ["alias_normalizado"], unique=False)
    op.create_index(op.f("ix_sku_alias_variacao_id"), "sku_alias", ["variacao_id"], unique=False)

    # ---------- Rastreio da migração ----------
    op.create_table(
        "de_para",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("origem", sa.String(length=120), nullable=False),
        sa.Column("id_origem", sa.String(length=80), nullable=False),
        sa.Column("tabela_destino", sa.String(length=40), nullable=False),
        sa.Column("id_destino", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("origem", "id_origem", "tabela_destino", name="uq_de_para_origem"),
    )
    op.create_index("ix_de_para_destino", "de_para", ["tabela_destino", "id_destino"], unique=False)

    op.create_table(
        "migracao_ocorrencias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo_problema", sa.String(length=60), nullable=False),
        sa.Column("dominio", sa.String(length=20), nullable=False),
        sa.Column("origem", sa.String(length=160), nullable=False),
        sa.Column("id_origem", sa.String(length=80), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("acao_tomada", sa.String(length=12), nullable=False),
        sa.Column("valor_original", sa.Text(), nullable=True),
        sa.Column("valor_final", sa.Text(), nullable=True),
        sa.Column("impacto", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("impacto_unidade", sa.String(length=10), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "acao_tomada IN ('CORRIGIDO', 'DESCARTADO', 'ESTIMADO', 'MANTIDO', 'PENDENTE')", name="ck_migracao_ocorrencias_acao"
        ),
        sa.CheckConstraint(
            "dominio IN ('lojas', 'produtos', 'clientes', 'usuarios', 'vendas', 'estoque', 'fidelidade', 'atendimento')",
            name="ck_migracao_ocorrencias_dominio",
        ),
        sa.CheckConstraint(
            "impacto_unidade IN ('REAIS', 'PONTOS', 'UNIDADES', 'REGISTROS')", name="ck_migracao_ocorrencias_unidade"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_migracao_ocorrencias_codigo_problema"), "migracao_ocorrencias", ["codigo_problema"], unique=False
    )
    op.create_index(op.f("ix_migracao_ocorrencias_dominio"), "migracao_ocorrencias", ["dominio"], unique=False)

    # ---------- Vulto+ ----------
    op.create_table(
        "contas_pontos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("saldo", sa.Integer(), server_default="0", nullable=False),
        sa.Column("categoria", sa.String(length=10), nullable=True),
        sa.Column("categoria_declarada", sa.String(length=40), nullable=True),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("categoria IN ('BRONZE', 'PRATA', 'OURO')", name="ck_contas_pontos_categoria"),
        sa.CheckConstraint("saldo >= 0", name="ck_contas_pontos_saldo"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cliente_id"),
    )
    op.create_table(
        "movimentos_pontos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conta_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("data", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vence_em", sa.Date(), nullable=True),
        sa.Column("pedido_id", sa.Integer(), nullable=True),
        sa.Column("origem", sa.String(length=160), server_default="", nullable=False),
        sa.Column("obs", sa.Text(), server_default="", nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "quantidade <> 0 AND (tipo NOT IN ('SALDO_INICIAL', 'CREDITO') OR quantidade > 0) "
            "AND (tipo NOT IN ('RESGATE', 'ESTORNO', 'VENCIMENTO') OR quantidade < 0)",
            name="ck_movimentos_pontos_sinal",
        ),
        sa.CheckConstraint(
            "tipo IN ('SALDO_INICIAL', 'CREDITO', 'RESGATE', 'ESTORNO', 'AJUSTE', 'VENCIMENTO')", name="ck_movimentos_pontos_tipo"
        ),
        sa.ForeignKeyConstraint(["conta_id"], ["contas_pontos.id"]),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_movimentos_pontos_conta_id"), "movimentos_pontos", ["conta_id"], unique=False)
    op.create_index(op.f("ix_movimentos_pontos_data"), "movimentos_pontos", ["data"], unique=False)
    op.create_index(op.f("ix_movimentos_pontos_pedido_id"), "movimentos_pontos", ["pedido_id"], unique=False)


def downgrade() -> None:
    """Volta a estrutura anterior. Só funciona antes da carga da Vulto: pedidos do App e lojas/produtos
    VULTO não cabem no schema antigo. Clientes sem e-mail recebem um endereço impossível de receber
    e-mail (como na conta excluída), para o e-mail voltar a ser obrigatório."""
    op.drop_index(op.f("ix_movimentos_pontos_pedido_id"), table_name="movimentos_pontos")
    op.drop_index(op.f("ix_movimentos_pontos_data"), table_name="movimentos_pontos")
    op.drop_index(op.f("ix_movimentos_pontos_conta_id"), table_name="movimentos_pontos")
    op.drop_table("movimentos_pontos")
    op.drop_table("contas_pontos")
    op.drop_index(op.f("ix_migracao_ocorrencias_dominio"), table_name="migracao_ocorrencias")
    op.drop_index(op.f("ix_migracao_ocorrencias_codigo_problema"), table_name="migracao_ocorrencias")
    op.drop_table("migracao_ocorrencias")
    op.drop_index("ix_de_para_destino", table_name="de_para")
    op.drop_table("de_para")
    op.drop_index(op.f("ix_sku_alias_variacao_id"), table_name="sku_alias")
    op.drop_index(op.f("ix_sku_alias_alias_normalizado"), table_name="sku_alias")
    op.drop_table("sku_alias")

    op.drop_column("clientes", "aceita_marketing_origem")
    op.drop_column("clientes", "aceita_marketing_em")
    op.drop_column("clientes", "aceita_marketing")
    op.drop_constraint("ck_clientes_identificador", "clientes", type_="check")
    op.execute("UPDATE clientes SET email = 'sem-email-' || id || '@clientes-sem-email.invalid' WHERE email IS NULL")
    op.alter_column("clientes", "email", existing_type=sa.VARCHAR(length=255), nullable=False)

    op.drop_constraint("ck_pedidos_canal", "pedidos", type_="check")
    op.create_check_constraint("ck_pedidos_canal", "pedidos", "canal IN ('Loja física', 'E-commerce')")

    op.drop_constraint("ck_variacoes_ean", "variacoes", type_="check")
    op.drop_constraint("variacoes_ean_key", "variacoes", type_="unique")
    op.drop_column("variacoes", "ean")
    op.drop_constraint("ck_produtos_marca", "produtos", type_="check")
    op.drop_index(op.f("ix_produtos_marca"), table_name="produtos")
    op.drop_column("produtos", "colecao")
    op.drop_column("produtos", "marca")
    op.drop_constraint("ck_lojas_tipo", "lojas", type_="check")
    op.drop_constraint("ck_lojas_marca", "lojas", type_="check")
    op.drop_index(op.f("ix_lojas_marca"), table_name="lojas")
    op.drop_column("lojas", "tipo")
    op.drop_column("lojas", "marca")
