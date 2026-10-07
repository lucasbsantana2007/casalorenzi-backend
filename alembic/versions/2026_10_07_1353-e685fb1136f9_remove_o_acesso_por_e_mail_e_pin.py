"""remove o acesso por e-mail e PIN ("Meus pedidos" legado)

O cliente entra com a conta (CPF, e-mail e senha) desde a conta do cliente; o frontend não usa
mais o PIN. Saem a tabela tokens_pin e as colunas de PIN de clientes (o check
ck_clientes_tentativas_pin cai junto com a coluna).

Revision ID: e685fb1136f9
Revises: bbfdeb8e8e3f
Create Date: 2026-10-07 13:53:25.476302

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e685fb1136f9"
down_revision: str | Sequence[str] | None = "bbfdeb8e8e3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_tokens_pin_cliente_id"), table_name="tokens_pin")
    op.drop_table("tokens_pin")
    op.drop_column("clientes", "bloqueado_ate")
    op.drop_column("clientes", "tentativas_pin")
    op.drop_column("clientes", "pin_hash")


def downgrade() -> None:
    """Volta a estrutura; os PINs antigos não voltam (os clientes criariam outro)."""
    op.add_column("clientes", sa.Column("pin_hash", sa.String(length=255), nullable=True))
    op.add_column("clientes", sa.Column("tentativas_pin", sa.Integer(), server_default="0", nullable=False))
    op.add_column("clientes", sa.Column("bloqueado_ate", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_clientes_tentativas_pin", "clientes", "tentativas_pin >= 0")
    op.create_table(
        "tokens_pin",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(op.f("ix_tokens_pin_cliente_id"), "tokens_pin", ["cliente_id"], unique=False)
