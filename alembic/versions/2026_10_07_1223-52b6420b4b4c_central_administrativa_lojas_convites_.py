"""central administrativa: lojas com detalhes, convite de funcionário, custo das peças, foto do
produto, frete configurável e log de ações

Revision ID: 52b6420b4b4c
Revises: 0fa54eed020f
Create Date: 2026-10-07 12:23:30.083517

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "52b6420b4b4c"
down_revision: str | Sequence[str] | None = "0fa54eed020f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Configuração de frete inicial (cópia fixa de FRETE_INICIAL, para a migração não mudar com o código):
# (regiao, nome, padrao valor/custo/prazo, expresso valor/custo/prazo)
_REGIOES = (
    ("SP", "Estado de São Paulo", "19.90", "16.50", 3, "39.90", "31.00", 1),
    ("SUDESTE", "Rio de Janeiro, Espírito Santo e Minas Gerais", "29.90", "24.00", 5, "59.90", "46.00", 2),
    ("SUL", "Região Sul", "34.90", "29.00", 6, "64.90", "52.00", 3),
    ("CENTRO_OESTE", "Região Centro-Oeste", "39.90", "33.00", 7, "74.90", "58.00", 3),
    ("NORDESTE", "Região Nordeste", "44.90", "38.00", 9, "84.90", "66.00", 4),
    ("NORTE", "Região Norte", "54.90", "47.00", 12, "99.90", "78.00", 5),
)


def upgrade() -> None:
    # Lojas: dados da página Lojas e status
    op.add_column("lojas", sa.Column("endereco", sa.String(length=255), server_default="", nullable=False))
    op.add_column("lojas", sa.Column("telefone", sa.String(length=30), server_default="", nullable=False))
    op.add_column("lojas", sa.Column("horarios", sa.JSON(), server_default="[]", nullable=False))
    op.add_column("lojas", sa.Column("ativa", sa.Boolean(), server_default="true", nullable=False))
    op.create_unique_constraint("lojas_nome_key", "lojas", ["nome"])

    # Funcionário novo nasce sem senha (convite pendente)
    op.alter_column("usuarios", "senha_hash", existing_type=sa.String(length=255), nullable=True)

    # Custo das peças e do frete (só o Administrador vê)
    op.add_column("variacoes", sa.Column("preco_custo", sa.Numeric(precision=10, scale=2), nullable=True))
    op.create_check_constraint("ck_variacoes_preco_custo", "variacoes", "preco_custo IS NULL OR preco_custo >= 0")
    op.add_column("pedidos", sa.Column("frete_custo", sa.Numeric(precision=10, scale=2), nullable=True))

    op.create_table(
        "imagens_produto",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("tamanho", sa.Integer(), nullable=False),
        sa.Column("dados", sa.LargeBinary(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("tipo IN ('image/jpeg', 'image/png', 'image/webp')", name="ck_imagens_produto_tipo"),
        sa.CheckConstraint("tamanho > 0 AND tamanho <= 2097152", name="ck_imagens_produto_tamanho"),
        sa.ForeignKeyConstraint(["produto_id"], ["produtos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("produto_id"),
    )

    config = op.create_table(
        "config_frete",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gratis_minimo", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("expresso_ativo", sa.Boolean(), nullable=False),
        sa.CheckConstraint("gratis_minimo >= 0", name="ck_config_frete_gratis_minimo"),
        sa.PrimaryKeyConstraint("id"),
    )
    regioes = op.create_table(
        "frete_regioes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("regiao", sa.String(length=20), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("padrao_valor", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("padrao_custo", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("padrao_prazo_dias", sa.Integer(), nullable=False),
        sa.Column("expresso_valor", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("expresso_custo", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("expresso_prazo_dias", sa.Integer(), nullable=False),
        sa.CheckConstraint("padrao_prazo_dias > 0 AND expresso_prazo_dias > 0", name="ck_frete_regioes_prazos"),
        sa.CheckConstraint(
            "padrao_valor >= 0 AND padrao_custo >= 0 AND expresso_valor >= 0 AND expresso_custo >= 0",
            name="ck_frete_regioes_valores",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("regiao"),
    )
    op.bulk_insert(config, [{"id": 1, "gratis_minimo": "1000.00", "expresso_ativo": True}])
    op.bulk_insert(
        regioes,
        [
            {
                "id": ordem,
                "regiao": regiao,
                "nome": nome,
                "ordem": ordem,
                "padrao_valor": pv,
                "padrao_custo": pc,
                "padrao_prazo_dias": pp,
                "expresso_valor": ev,
                "expresso_custo": ec,
                "expresso_prazo_dias": ep,
            }
            for ordem, (regiao, nome, pv, pc, pp, ev, ec, ep) in enumerate(_REGIOES, start=1)
        ],
    )
    op.execute("SELECT setval(pg_get_serial_sequence('frete_regioes', 'id'), (SELECT MAX(id) FROM frete_regioes))")

    op.create_table(
        "log_acoes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("area", sa.String(length=20), nullable=False),
        sa.Column("acao", sa.String(length=30), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("alteracoes", sa.JSON(), nullable=False),
        sa.Column("referencia_tipo", sa.String(length=30), nullable=True),
        sa.Column("referencia_id", sa.Integer(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "area IN ('FUNCIONARIOS', 'LOJAS', 'FRETE', 'PRODUTOS', 'PEDIDOS', 'TRANSFERENCIAS', 'ESTOQUE')",
            name="ck_log_acoes_area",
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_log_acoes_area", "log_acoes", ["area"])
    op.create_index("ix_log_acoes_criado_em", "log_acoes", ["criado_em"])
    op.create_index("ix_log_acoes_usuario_id", "log_acoes", ["usuario_id"])


def downgrade() -> None:
    op.drop_index("ix_log_acoes_usuario_id", table_name="log_acoes")
    op.drop_index("ix_log_acoes_criado_em", table_name="log_acoes")
    op.drop_index("ix_log_acoes_area", table_name="log_acoes")
    op.drop_table("log_acoes")
    op.drop_table("frete_regioes")
    op.drop_table("config_frete")
    op.drop_table("imagens_produto")
    op.drop_column("pedidos", "frete_custo")
    op.drop_constraint("ck_variacoes_preco_custo", "variacoes", type_="check")
    op.drop_column("variacoes", "preco_custo")
    # Convites pendentes ficam com um hash vazio, que nunca confere com nenhuma senha
    op.execute("UPDATE usuarios SET senha_hash = '' WHERE senha_hash IS NULL")
    op.alter_column("usuarios", "senha_hash", existing_type=sa.String(length=255), nullable=False)
    op.drop_constraint("lojas_nome_key", "lojas", type_="unique")
    op.drop_column("lojas", "ativa")
    op.drop_column("lojas", "horarios")
    op.drop_column("lojas", "telefone")
    op.drop_column("lojas", "endereco")
