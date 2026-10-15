"""atendimento da Vulto

- atendimentos: canal (SITE nos da Casa Lorenzi; WHATSAPP, INSTAGRAM, EMAIL nos da Vulto), contato e
  contato_nome (como o cliente se identificou) e cliente opcional (contato que não identifica ninguém:
  @ do Instagram, telefone sem DDD); sempre há o cliente ou o contato.
- usuarios: e-mail opcional para os funcionários da Vulto, que vieram sem e-mail; usuário ativo
  sempre tem e-mail.

Revision ID: 5f9f168279bc
Revises: 47e699995ac8
Create Date: 2026-10-15 11:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f9f168279bc"
down_revision: str | Sequence[str] | None = "47e699995ac8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("atendimentos", sa.Column("canal", sa.String(length=20), server_default="SITE", nullable=False))
    op.add_column("atendimentos", sa.Column("contato", sa.String(length=255), nullable=True))
    op.add_column("atendimentos", sa.Column("contato_nome", sa.String(length=120), nullable=True))
    op.create_index(op.f("ix_atendimentos_contato"), "atendimentos", ["contato"], unique=False)
    op.create_check_constraint("ck_atendimentos_canal", "atendimentos", "canal IN ('SITE', 'WHATSAPP', 'INSTAGRAM', 'EMAIL')")
    op.alter_column("atendimentos", "cliente_id", existing_type=sa.INTEGER(), nullable=True)
    op.create_check_constraint("ck_atendimentos_cliente_ou_contato", "atendimentos", "cliente_id IS NOT NULL OR contato IS NOT NULL")

    op.alter_column("usuarios", "email", existing_type=sa.String(length=255), nullable=True)
    op.create_check_constraint("ck_usuarios_email_ativo", "usuarios", "email IS NOT NULL OR NOT ativo")


def downgrade() -> None:
    """Só funciona antes da carga do atendimento e dos funcionários da Vulto (atendimento sem cliente e
    funcionário sem e-mail não cabem no schema antigo)."""
    op.drop_constraint("ck_usuarios_email_ativo", "usuarios", type_="check")
    op.alter_column("usuarios", "email", existing_type=sa.String(length=255), nullable=False)

    op.drop_constraint("ck_atendimentos_cliente_ou_contato", "atendimentos", type_="check")
    op.alter_column("atendimentos", "cliente_id", existing_type=sa.INTEGER(), nullable=False)
    op.drop_constraint("ck_atendimentos_canal", "atendimentos", type_="check")
    op.drop_index(op.f("ix_atendimentos_contato"), table_name="atendimentos")
    op.drop_column("atendimentos", "contato_nome")
    op.drop_column("atendimentos", "contato")
    op.drop_column("atendimentos", "canal")
