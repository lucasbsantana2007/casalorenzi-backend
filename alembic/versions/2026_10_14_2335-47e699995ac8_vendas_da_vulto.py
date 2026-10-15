"""vendas da Vulto

- pedidos: desconto (zero nos da Casa Lorenzi), tipo (VENDA | TROCA: a troca lançada como venda nova
  movimenta o estoque mas não é receita), pedido_externo (número no site/app da Vulto) e cliente
  opcional (vendas da Vulto sem cliente identificável).
- devolucoes: pedido, item e usuário opcionais (devoluções da Vulto sem venda de origem, registradas
  sem usuário), com a variação devolvida em variacao_id; sempre há o item ou a variação.

Revision ID: 47e699995ac8
Revises: b14cf28501fc
Create Date: 2026-10-14 23:35:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "47e699995ac8"
down_revision: str | Sequence[str] | None = "b14cf28501fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pedidos", sa.Column("desconto", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False))
    op.add_column("pedidos", sa.Column("tipo", sa.String(length=10), server_default="VENDA", nullable=False))
    op.add_column("pedidos", sa.Column("pedido_externo", sa.String(length=40), nullable=True))
    op.create_index(op.f("ix_pedidos_pedido_externo"), "pedidos", ["pedido_externo"], unique=False)
    op.create_check_constraint("ck_pedidos_tipo", "pedidos", "tipo IN ('VENDA', 'TROCA')")
    op.create_check_constraint("ck_pedidos_desconto", "pedidos", "desconto >= 0")
    op.alter_column("pedidos", "cliente_id", existing_type=sa.INTEGER(), nullable=True)

    op.add_column("devolucoes", sa.Column("variacao_id", sa.Integer(), nullable=True))
    op.create_foreign_key("devolucoes_variacao_id_fkey", "devolucoes", "variacoes", ["variacao_id"], ["id"])
    op.alter_column("devolucoes", "item_pedido_id", existing_type=sa.INTEGER(), nullable=True)
    op.alter_column("devolucoes", "pedido_id", existing_type=sa.INTEGER(), nullable=True)
    op.alter_column("devolucoes", "usuario_id", existing_type=sa.INTEGER(), nullable=True)
    op.create_check_constraint("ck_devolucoes_peca", "devolucoes", "item_pedido_id IS NOT NULL OR variacao_id IS NOT NULL")


def downgrade() -> None:
    """Só funciona antes da carga das vendas da Vulto (pedidos sem cliente, trocas e devoluções sem
    origem não cabem no schema antigo)."""
    op.drop_constraint("ck_devolucoes_peca", "devolucoes", type_="check")
    op.alter_column("devolucoes", "usuario_id", existing_type=sa.INTEGER(), nullable=False)
    op.alter_column("devolucoes", "pedido_id", existing_type=sa.INTEGER(), nullable=False)
    op.alter_column("devolucoes", "item_pedido_id", existing_type=sa.INTEGER(), nullable=False)
    op.drop_constraint("devolucoes_variacao_id_fkey", "devolucoes", type_="foreignkey")
    op.drop_column("devolucoes", "variacao_id")

    op.alter_column("pedidos", "cliente_id", existing_type=sa.INTEGER(), nullable=False)
    op.drop_constraint("ck_pedidos_desconto", "pedidos", type_="check")
    op.drop_constraint("ck_pedidos_tipo", "pedidos", type_="check")
    op.drop_index(op.f("ix_pedidos_pedido_externo"), table_name="pedidos")
    op.drop_column("pedidos", "pedido_externo")
    op.drop_column("pedidos", "tipo")
    op.drop_column("pedidos", "desconto")
