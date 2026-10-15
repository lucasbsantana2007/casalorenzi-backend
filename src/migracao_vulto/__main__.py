"""Linha de comando da migração da Vulto (uma transação por domínio).

    python -m src.migracao_vulto --tudo
    python -m src.migracao_vulto --dominio staging   # só a cópia crua do legado (schema legado_vulto)
    python -m src.migracao_vulto --dominio lojas

Os dados do legado vêm da pasta VULTO_DADOS (padrão: ../vulto-legado-back/data).

Contra o banco de produção, rode do seu computador com a URL externa do banco:
    DATABASE_URL="postgresql+psycopg://..." python -m src.migracao_vulto --tudo
"""

import argparse
from collections.abc import Callable

from sqlalchemy.orm import Session

from src.database.connection import SessionLocal
from src.entities.migracao import DOMINIOS_MIGRACAO
from src.migracao_vulto import clientes, lojas, produtos, staging, vendas
from src.migracao_vulto.relatorio import Resultado, formatar

# Domínios implementados, na ordem de DOMINIOS_MIGRACAO (os outros chegam etapa por etapa)
MIGRADORES: dict[str, Callable[[Session], Resultado]] = {
    staging.DOMINIO: staging.migrar,
    lojas.DOMINIO: lojas.migrar,
    produtos.DOMINIO: produtos.migrar,
    clientes.DOMINIO: clientes.migrar,
    vendas.DOMINIO: vendas.migrar,
}


def rodar(dominios: list[str]) -> list[Resultado]:
    resultados = []
    for dominio in dominios:
        with SessionLocal() as db:
            resultado = MIGRADORES[dominio](db)
            db.commit()
        resultados.append(resultado)
    return resultados


def main() -> None:
    disponiveis = [d for d in DOMINIOS_MIGRACAO if d in MIGRADORES]
    parser = argparse.ArgumentParser(description="Migra os dados da Vulto para a plataforma (idempotente).")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--tudo", action="store_true", help="roda todos os domínios, na ordem")
    grupo.add_argument("--dominio", choices=disponiveis, help="roda só um domínio")
    args = parser.parse_args()

    resultados = rodar(disponiveis if args.tudo else [args.dominio])
    print(formatar(resultados))


if __name__ == "__main__":
    main()
