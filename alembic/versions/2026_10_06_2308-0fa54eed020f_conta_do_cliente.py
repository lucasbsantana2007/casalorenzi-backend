"""conta do cliente: CPF, senha e links de "esqueci a senha"

- clientes ganha cpf (11 dígitos, único) e senha_hash. Os dois ficam nulos nos clientes
  antigos, sem conta: eles continuam consultando "Meus pedidos" com e-mail + PIN e podem
  criar a senha pelo "esqueci a senha".
- Nova tabela tokens_senha: link de uso único e com validade para trocar a senha, da equipe
  (usuario_id) ou de um cliente (cliente_id).

Revision ID: 0fa54eed020f
Revises: 845b5ed3da0c
Create Date: 2026-10-06 23:08:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0fa54eed020f"
down_revision: str | Sequence[str] | None = "845b5ed3da0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clientes", sa.Column("cpf", sa.String(length=11), nullable=True))
    op.add_column("clientes", sa.Column("senha_hash", sa.String(length=255), nullable=True))
    op.create_unique_constraint("clientes_cpf_key", "clientes", ["cpf"])
    op.create_check_constraint("ck_clientes_cpf", "clientes", "cpf IS NULL OR cpf ~ '^[0-9]{11}$'")

    op.create_table(
        "tokens_senha",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("cliente_id", sa.Integer(), nullable=True),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(usuario_id IS NULL) <> (cliente_id IS NULL)", name="ck_tokens_senha_dono"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(op.f("ix_tokens_senha_cliente_id"), "tokens_senha", ["cliente_id"], unique=False)
    op.create_index(op.f("ix_tokens_senha_usuario_id"), "tokens_senha", ["usuario_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tokens_senha_usuario_id"), table_name="tokens_senha")
    op.drop_index(op.f("ix_tokens_senha_cliente_id"), table_name="tokens_senha")
    op.drop_table("tokens_senha")
    op.drop_constraint("ck_clientes_cpf", "clientes", type_="check")
    op.drop_constraint("clientes_cpf_key", "clientes", type_="unique")
    op.drop_column("clientes", "senha_hash")
    op.drop_column("clientes", "cpf")
