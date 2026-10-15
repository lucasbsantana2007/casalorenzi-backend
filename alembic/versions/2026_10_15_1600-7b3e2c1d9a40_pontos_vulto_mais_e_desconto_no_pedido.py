"""pontos Vulto+ e desconto no pedido

Extrato de pontos do Vulto+ (movimentos com sinal e saldo resultante que não fica negativo) e o
desconto do resgate de pontos no pedido (total = subtotal − desconto + frete). Pedidos existentes
ficam com desconto zero.

Revision ID: 7b3e2c1d9a40
Revises: e685fb1136f9
Create Date: 2026-10-15 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b3e2c1d9a40"
down_revision: str | Sequence[str] | None = "e685fb1136f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pedidos", sa.Column("desconto", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False))
    op.create_check_constraint("ck_pedidos_desconto", "pedidos", "desconto >= 0 AND desconto <= subtotal")
    op.create_table(
        "movimentos_pontos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("saldo_resultante", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.Integer(), nullable=True),
        sa.Column("obs", sa.String(length=255), server_default="", nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "tipo IN ('SALDO_INICIAL', 'CREDITO', 'RESGATE', 'ESTORNO', 'AJUSTE')", name="ck_movimentos_pontos_tipo"
        ),
        sa.CheckConstraint("quantidade <> 0", name="ck_movimentos_pontos_quantidade"),
        sa.CheckConstraint("saldo_resultante >= 0", name="ck_movimentos_pontos_saldo"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_movimentos_pontos_cliente_id"), "movimentos_pontos", ["cliente_id"], unique=False)
    op.create_index(op.f("ix_movimentos_pontos_pedido_id"), "movimentos_pontos", ["pedido_id"], unique=False)
    op.create_index(op.f("ix_movimentos_pontos_criado_em"), "movimentos_pontos", ["criado_em"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_movimentos_pontos_criado_em"), table_name="movimentos_pontos")
    op.drop_index(op.f("ix_movimentos_pontos_pedido_id"), table_name="movimentos_pontos")
    op.drop_index(op.f("ix_movimentos_pontos_cliente_id"), table_name="movimentos_pontos")
    op.drop_table("movimentos_pontos")
    op.drop_constraint("ck_pedidos_desconto", "pedidos", type_="check")
    op.drop_column("pedidos", "desconto")
