"""equipe de demonstração das duas marcas

Cada marca passa a ter a equipe completa na demonstração, a mesma do seed (src/database/seed/dados.py):
o Administrador só da Casa Lorenzi (Otávio Vasconcelos), a Administradora da Vulto (Paula Ferraz), a
Lojista da Vulto Pinheiros (Lia Okada) e o Operador do CD Cajamar (Bruno Sales), com a senha das outras
contas de demonstração.

Só vale para o banco que já tem a demonstração (a Helena do seed). Num banco novo, quem cria a equipe é
o seed e, depois da carga da Vulto, src/database/seed/equipe_vulto.py. Só cria quem ainda não existe
(pelo e-mail); sem as lojas da Vulto (carga ainda não feita), a Lia e o Bruno ficam de fora.

Revision ID: d9e3f7a1b5c8
Revises: c4e8a2f6b1d3
Create Date: 2026-10-22 21:00:00
"""

from collections.abc import Sequence

import bcrypt
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e3f7a1b5c8"
down_revision: str | Sequence[str] | None = "c4e8a2f6b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SENHA_DEMO = "lorenzi2026"
# (nome, e-mail, papel, marca, loja)
EQUIPE = [
    ("Otávio Vasconcelos", "otavio.vasconcelos@casalorenzi.com.br", "ADMINISTRADOR", "LORENZI", None),
    ("Paula Ferraz", "paula.ferraz@vulto.com.br", "ADMINISTRADOR", "VULTO", None),
    ("Lia Okada", "lia.okada@vulto.com.br", "LOJISTA", "VULTO", "Vulto Pinheiros"),
    ("Bruno Sales", "bruno.sales@vulto.com.br", "OPERADOR", "VULTO", "CD Cajamar"),
]


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM usuarios WHERE email = 'helena@casalorenzi.com.br')")):
        return
    senha = bcrypt.hashpw(SENHA_DEMO.encode(), bcrypt.gensalt()).decode()
    for nome, email, papel, marca, loja in EQUIPE:
        if conn.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM usuarios WHERE email = :email)"), {"email": email}):
            continue
        loja_id = None
        if loja:
            loja_id = conn.scalar(
                sa.text("SELECT id FROM lojas WHERE nome = :nome AND marca = :marca"), {"nome": loja, "marca": marca}
            )
            if loja_id is None:
                continue
        conn.execute(
            sa.text(
                "INSERT INTO usuarios (nome, email, senha_hash, papel, ativo, marca, loja_id) "
                "VALUES (:nome, :email, :senha, :papel, true, :marca, :loja_id)"
            ),
            {"nome": nome, "email": email, "senha": senha, "papel": papel, "marca": marca, "loja_id": loja_id},
        )


def downgrade() -> None:
    """Não apaga ninguém: a essa altura, a equipe pode ter registros no painel (log, atendimentos)."""
