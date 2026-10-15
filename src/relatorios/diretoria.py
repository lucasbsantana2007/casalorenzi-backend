"""Gera os números da diretoria sobre a Vulto em arquivos: numeros.json e um CSV por seção (Excel em
português: ";", vírgula decimal, UTF-8 com BOM).

    python -m src.relatorios.diretoria --saida docs/numeros_diretoria

Rode depois da migração (`python -m src.migracao_vulto --tudo`), contra o banco que tem os dados.
"""

import argparse
import json
from pathlib import Path

from src.database.connection import SessionLocal
from src.use_cases import diretoria


def gerar(pasta: Path) -> list[Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        dados = diretoria.numeros(db)
    arquivos = [pasta / "numeros.json"]
    arquivos[0].write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for secao in diretoria.SECOES_CSV:
        arquivo = pasta / f"{secao.replace('-', '_')}.csv"
        arquivo.write_text(diretoria.csv_da_secao(dados, secao), encoding="utf-8", newline="")
        arquivos.append(arquivo)
    return arquivos


def main() -> None:
    parser = argparse.ArgumentParser(description="Números da diretoria sobre a Vulto (JSON e CSV).")
    parser.add_argument("--saida", default="docs/numeros_diretoria", help="pasta de saída (padrão: docs/numeros_diretoria)")
    for arquivo in gerar(Path(parser.parse_args().saida)):
        print(arquivo)


if __name__ == "__main__":
    main()
