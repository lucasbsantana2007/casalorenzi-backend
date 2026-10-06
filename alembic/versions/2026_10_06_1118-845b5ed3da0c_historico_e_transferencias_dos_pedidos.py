"""historico dos pedidos e transferencias ligadas ao pedido

- Nova tabela `eventos_pedido`: histórico de cada pedido (status, quem mudou, quando e
  observação). Mostrado no detalhe do pedido no painel e, sem os dados internos, em
  "Meus pedidos". Pedidos antigos ficam sem eventos: a API mostra o status atual na data
  de criação.
- `transferencias.pedido_id`: liga as transferências automáticas do e-commerce (peças que
  faltam na loja de expedição) ao pedido que as originou. Nula nas transferências manuais.

Revision ID: 845b5ed3da0c
Revises: c41d7e9a2b58
Create Date: 2026-10-06 11:18:27.495175

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "845b5ed3da0c"
down_revision: str | Sequence[str] | None = "c41d7e9a2b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eventos_pedido",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("observacao", sa.Text(), server_default="", nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('PROCESSANDO', 'ENVIADO', 'ENTREGUE', 'CANCELADO')", name="ck_eventos_pedido_status"),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_eventos_pedido_pedido_id"), "eventos_pedido", ["pedido_id"], unique=False)

    op.add_column("transferencias", sa.Column("pedido_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_transferencias_pedido_id"), "transferencias", ["pedido_id"], unique=False)
    op.create_foreign_key("fk_transferencias_pedido_id", "transferencias", "pedidos", ["pedido_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_transferencias_pedido_id", "transferencias", type_="foreignkey")
    op.drop_index(op.f("ix_transferencias_pedido_id"), table_name="transferencias")
    op.drop_column("transferencias", "pedido_id")
    op.drop_index(op.f("ix_eventos_pedido_pedido_id"), table_name="eventos_pedido")
    op.drop_table("eventos_pedido")
