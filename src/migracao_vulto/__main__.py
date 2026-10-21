"""Carga única dos dados da Vulto (regras e garantias em src/migracao_vulto/carga.py).

    python -m src.migracao_vulto --origem ../copy.vulto-legado-back --simular   # roda tudo e desfaz no fim
    python -m src.migracao_vulto --origem ../copy.vulto-legado-back             # grava, se tudo bater

O banco é o do DATABASE_URL (.env). Para o banco do Render, use a "External Database URL" dele:
    DATABASE_URL="postgresql+psycopg://..." python -m src.migracao_vulto --origem ...
"""

import argparse
import sys
import time
from pathlib import Path

from src.database.connection import SessionLocal
from src.migracao_vulto.carga import Carga, CargaRecusada

RAIZ = Path(__file__).resolve().parents[2]


def main() -> int:
    args = argparse.ArgumentParser(description="Carga única dos dados da Vulto na plataforma.")
    args.add_argument("--origem", required=True, help="pasta do repositório copy.vulto-legado-back")
    args.add_argument("--simular", action="store_true", help="roda e confere tudo, mas não grava nada")
    args = args.parse_args()

    inicio = time.monotonic()
    with SessionLocal() as db:
        try:
            relatorio = Carga(db, Path(args.origem).expanduser(), RAIZ / "docs" / "registro_decisoes_uniao.md").executar()
        except CargaRecusada as erro:
            db.rollback()
            print(f"Carga recusada, nada foi gravado: {erro}")
            return 1
        print("\n".join(relatorio.linhas()))
        if args.simular:
            db.rollback()
            print(f"Simulação: tudo bateu e nada foi gravado ({time.monotonic() - inicio:.0f}s).")
        else:
            db.commit()
            print(f"Carga gravada ({time.monotonic() - inicio:.0f}s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
