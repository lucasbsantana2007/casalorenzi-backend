"""Roda as automações operacionais (alertas de estoque, transferências, pontos e a limpeza das conversas).

    python -m src.automacoes                   # todas
    python -m src.automacoes estoque_baixo     # uma só
    python -m src.automacoes --forcar estoque_baixo

Feito para um agendador (Render Cron Job, GitHub Actions, cron do servidor) com o mesmo DATABASE_URL da API.
Cada automação roda uma vez por vez (trava no Postgres) e não duplica alertas: rodar de novo é seguro.
Sai com código 1 se alguma falhar.
"""

import argparse
import logging
import sys

from src.config.settings import LOG_LEVEL
from src.use_cases import automacoes


def main() -> int:
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Automações operacionais da plataforma")
    parser.add_argument("nomes", nargs="*", help="Automações (padrão: todas)")
    parser.add_argument("--forcar", action="store_true", help="Roda mesmo que tenha rodado há menos de um minuto")
    args = parser.parse_args()
    nomes = args.nomes or list(automacoes.AUTOMACOES)
    desconhecidas = [n for n in nomes if n not in automacoes.AUTOMACOES]
    if desconhecidas:
        print(f"Automação desconhecida: {', '.join(desconhecidas)}. Opções: {', '.join(automacoes.AUTOMACOES)}")
        return 2
    falhou = False
    for nome in nomes:
        execucao = automacoes.executar(nome, forcar=args.forcar)
        print(
            f"{nome:26} {execucao.status:10} +{execucao.criados} ~{execucao.atualizados} ✓{execucao.resolvidos}  {execucao.detalhe}"
        )
        falhou = falhou or execucao.status == "ERRO"
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
