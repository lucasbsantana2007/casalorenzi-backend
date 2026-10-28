"""Avaliação da Lúcia com o Claude de verdade (decisão 105): os casos de tests/bateria_lucia.py, cada um numa
conversa nova, no banco de testes recriado a partir do seed. Gera o placar em docs/avaliacao_lucia.md.

    python scripts/avaliar_lucia.py                  # todos os casos
    python scripts/avaliar_lucia.py --casos 1 5 28   # só alguns
    python scripts/avaliar_lucia.py --modelo claude-sonnet-5-5

Quando rodar: antes de mexer no prompt, nas ferramentas, nas regras ou no modelo, e de novo depois; o placar não
pode cair. Usa TEST_DATABASE_URL (nunca o banco de desenvolvimento nem o de produção) e ANTHROPIC_API_KEY do .env.
Custa poucos centavos de dólar por rodada (o placar mostra o custo medido). Nada sai do banco de testes: não manda
e-mail nem abre atendimento de verdade.
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
load_dotenv(RAIZ / ".env")
if not os.getenv("TEST_DATABASE_URL"):
    sys.exit("Defina TEST_DATABASE_URL no .env: a avaliação recria o banco de testes a cada caso.")
if not os.getenv("ANTHROPIC_API_KEY"):
    sys.exit("Defina ANTHROPIC_API_KEY no .env: a avaliação é com o modelo de verdade (sem ele, rode o pytest).")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]  # antes de importar o app
os.environ["RESEND_API_KEY"] = ""  # nenhum e-mail de verdade


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--casos", type=int, nargs="*", help="Números dos casos (padrão: todos)")
    parser.add_argument("--modelo", help="Outro modelo para comparar (padrão: IA_MODELO do .env)")
    parser.add_argument("--saida", default=str(RAIZ / "docs" / "avaliacao_lucia.md"))
    args = parser.parse_args()
    if args.modelo:
        os.environ["IA_MODELO"] = args.modelo
    sys.stdout.reconfigure(encoding="utf-8")

    from alembic.config import Config
    from fastapi.testclient import TestClient

    from alembic import command
    from src.app import app
    from src.config import settings
    from src.database.connection import SessionLocal
    from src.database.seed import apagar_tudo, popular
    from src.middlewares import limite
    from tests.bateria_lucia import CASOS, rodar
    from tests.util_assistente import sql

    command.upgrade(Config(str(RAIZ / "alembic.ini")), "head")
    casos = [c for c in CASOS if not args.casos or c.numero in args.casos]
    client = TestClient(app)
    linhas = []
    for caso in casos:
        limite.limpar()
        with SessionLocal() as db:
            apagar_tudo(db)
            popular(db)
            db.commit()
        inicio = time.perf_counter()
        try:
            resposta, faltas = rodar(client, caso)
        except AssertionError as erro:  # a API respondeu erro (ex.: 429): o caso conta como falha
            resposta, faltas = {"texto": "", "blocos": [], "modo": "ERRO", "conversaId": None}, [f"erro na API: {erro}"]
        segundos = time.perf_counter() - inicio
        consumo = (
            sql(
                "SELECT count(*), coalesce(sum(custo_estimado), 0), coalesce(sum(duracao_ms), 0) FROM consumo_ia "
                "WHERE conversa_id = :c",
                c=resposta["conversaId"],
            )[0]
            if resposta.get("conversaId")
            else (0, 0, 0)
        )
        auditoria = {}
        if resposta.get("id"):
            auditoria = sql("SELECT auditoria FROM mensagens_assistente WHERE id = :m", m=resposta["id"])[0][0] or {}
        linhas.append(
            {
                "caso": caso,
                "ok": not faltas,
                "faltas": faltas,
                "texto": resposta["texto"],
                "blocos": [b["tipo"] for b in resposta["blocos"]],
                "modo": resposta["modo"],
                "verificacao": auditoria.get("verificacao"),
                "semFonte": auditoria.get("semFonte"),
                "chamadas": int(consumo[0]),
                "custo": float(consumo[1]),
                "segundos": segundos,
            }
        )
        marca = "ok " if not faltas else "ERRO"
        print(f"{marca} #{caso.numero:02d} {caso.pergunta[:60]!r} {segundos:.1f}s {faltas or ''}")

    texto = relatorio(linhas, settings.IA_MODELO)
    Path(args.saida).write_text(texto, encoding="utf-8")
    acertos = sum(1 for linha in linhas if linha["ok"])
    custo = sum(linha["custo"] for linha in linhas)
    print(f"\nPlacar: {acertos} de {len(linhas)}. Custo: US$ {_num(custo, 4)}. Relatório: {args.saida}")


def _celula(texto: str, limite: int = 220) -> str:
    texto = " ".join((texto or "").split()).replace("|", "/")
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def _num(valor: float, casas: int) -> str:
    """Com vírgula, como no resto da documentação: 0,0138."""
    return f"{valor:.{casas}f}".replace(".", ",")


def relatorio(linhas: list[dict], modelo: str) -> str:
    acertos = sum(1 for linha in linhas if linha["ok"])
    custo = sum(linha["custo"] for linha in linhas)
    tempos = sorted(linha["segundos"] for linha in linhas)
    p90 = tempos[min(len(tempos) - 1, int(len(tempos) * 0.9))] if tempos else 0
    verificacao = {
        situacao: sum(1 for linha in linhas if linha["verificacao"] == situacao)
        for situacao in ("CONFERIDA", "REESCRITA", "SUBSTITUIDA")
    }
    partes = [
        "# Avaliação da Lúcia com o Claude",
        "",
        f"Gerado por `scripts/avaliar_lucia.py` em {datetime.now():%d/%m/%Y %H:%M}, modelo `{modelo}`, no banco de testes "
        "(seed de demonstração). Os casos e o que cada resposta precisa ter estão em `tests/bateria_lucia.py` (decisão 105); "
        "a mesma bateria roda sem o Claude no pytest (`tests/test_bateria_lucia.py`).",
        "",
        f"**Placar: {acertos} de {len(linhas)}.** Custo medido: US$ {_num(custo, 4)} "
        f"(US$ {_num(custo / max(1, len(linhas)), 5)} por caso). Tempo por caso: médio "
        f"{_num(sum(tempos) / max(1, len(tempos)), 1)} s, 90% até {_num(p90, 1)} s (inclui as mensagens de antes da "
        "pergunta, quando o caso tem).",
        "",
        f"Verificador de números (decisão 101) nas respostas do modelo: {verificacao['CONFERIDA']} conferidas de primeira, "
        f"{verificacao['REESCRITA']} refeitas pelo modelo e {verificacao['SUBSTITUIDA']} trocadas pelo texto das consultas.",
        "",
        "| # | Assunto | Pergunta | Resultado | Modo | Números | s | Resposta |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for linha in linhas:
        caso = linha["caso"]
        resultado = "✅" if linha["ok"] else "❌ " + _celula("; ".join(linha["faltas"]), 120)
        numeros = linha["verificacao"] or "—"
        if linha["semFonte"]:
            numeros += f" (sem fonte: {', '.join(linha['semFonte'])})"
        partes.append(
            f"| {caso.numero} | {caso.assunto} | {_celula(caso.pergunta, 80)} | {resultado} | {linha['modo']} | {numeros} | "
            f"{_num(linha['segundos'], 1)} | {_celula(linha['texto'])} |"
        )
    falhas = [linha for linha in linhas if not linha["ok"]]
    if falhas:
        partes += ["", "## O que falhou", ""]
        for linha in falhas:
            caso = linha["caso"]
            partes += [
                f"### {caso.numero}. {caso.pergunta}",
                f"- **Esperado:** {caso.esperado}",
                f"- **Faltou:** {'; '.join(linha['faltas'])}",
                f"- **Blocos:** {', '.join(linha['blocos']) or 'nenhum'}",
                f"- **Resposta:** {_celula(linha['texto'], 800)}",
                "",
            ]
    return "\n".join(partes) + "\n"


if __name__ == "__main__":
    main()
