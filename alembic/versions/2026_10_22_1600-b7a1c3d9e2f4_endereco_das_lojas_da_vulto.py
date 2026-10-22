"""endereço, telefone e horários das lojas da Vulto

O sistema da Vulto só guardava nome e cidade das lojas, e a página Lojas do site (/vulto/lojas) mostra
endereço, telefone e horários ao abrir cada uma. Dados de demonstração do case, os mesmos da carga
(src/migracao_vulto/carga.py, CONTATO_LOJAS). Só completa o que está vazio: não sobrescreve loja já
editada na central administrativa. Banco sem as lojas da Vulto (carga ainda não feita): não muda nada.

Revision ID: b7a1c3d9e2f4
Revises: f060e5b0d838
Create Date: 2026-10-22 16:00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7a1c3d9e2f4"
down_revision: str | Sequence[str] | None = "f060e5b0d838"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTATO = {
    "Vulto Pinheiros": (
        "Rua dos Pinheiros, 1037 - Pinheiros, São Paulo - SP",
        "+55 11 94102-3381",
        ["Segunda a sábado: 10:00–21:00", "Domingo: 12:00–19:00"],
    ),
    "Vulto Shopping Eldorado": (
        "Av. Rebouças, 3970, Piso Térreo - Pinheiros, São Paulo - SP",
        "+55 11 94102-3392",
        ["Segunda a sábado: 10:00–22:00", "Domingo: 14:00–20:00"],
    ),
    "Vulto Savassi": (
        "Rua Pernambuco, 1000 - Savassi, Belo Horizonte - MG",
        "+55 31 98820-4410",
        ["Segunda a sábado: 10:00–20:00"],
    ),
    "Vulto Batel": (
        "Av. do Batel, 1550 - Batel, Curitiba - PR",
        "+55 41 99731-2207",
        ["Segunda a sábado: 10:00–20:00", "Domingo: 12:00–18:00"],
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    for nome, (endereco, telefone, horarios) in CONTATO.items():
        conn.execute(
            sa.text(
                "UPDATE lojas SET endereco = :endereco, telefone = :telefone, horarios = CAST(:horarios AS JSON) "
                "WHERE nome = :nome AND marca = 'VULTO' AND endereco = ''"
            ),
            {"nome": nome, "endereco": endereco, "telefone": telefone, "horarios": json.dumps(horarios, ensure_ascii=False)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for nome, (endereco, _, _) in CONTATO.items():
        conn.execute(
            sa.text("UPDATE lojas SET endereco = '', telefone = '', horarios = CAST('[]' AS JSON) WHERE nome = :nome AND endereco = :endereco"),
            {"nome": nome, "endereco": endereco},
        )
