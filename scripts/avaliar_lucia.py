"""Avaliação da Lúcia com o Claude de verdade (decisão 105): os casos de tests/bateria_lucia.py, cada um numa
conversa nova, no banco de testes recriado a partir do seed. Gera o placar em docs/avaliacao_lucia.md.

    python scripts/avaliar_lucia.py                  # todos os casos
    python scripts/avaliar_lucia.py --casos 1 5 28   # só alguns
    python scripts/avaliar_lucia.py --modelo claude-sonnet-5-5
    python scripts/avaliar_lucia.py --reconferir relatorios/avaliacao_lucia.json   # sem chamar o modelo

Quando rodar: antes de mexer no prompt, nas ferramentas, nas regras ou no modelo, e de novo depois; o placar não
pode cair. Usa TEST_DATABASE_URL (nunca o banco de desenvolvimento nem o de produção) e ANTHROPIC_API_KEY do .env.
Custa poucos centavos de dólar por rodada (o placar mostra o custo medido). Nada sai do banco de testes: não manda
e-mail nem abre atendimento de verdade.

As respostas ficam guardadas em relatorios/avaliacao_lucia.json (fora do git). Ao ajustar uma conferência da bateria
(o modelo disse a coisa certa com outras palavras), --reconferir refaz o placar sobre essas respostas, sem pagar o
modelo de novo.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
load_dotenv(RAIZ / ".env")
RESPOSTAS = RAIZ / "relatorios" / "avaliacao_lucia.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--casos", type=int, nargs="*", help="Números dos casos (padrão: todos)")
    parser.add_argument("--modelo", help="Outro modelo para comparar (padrão: IA_MODELO do .env)")
    parser.add_argument("--saida", default=str(RAIZ / "docs" / "avaliacao_lucia.md"))
    parser.add_argument("--reconferir", help="Refaz as conferências sobre respostas guardadas (sem modelo e sem banco)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.getenv("TEST_DATABASE_URL"):
        sys.exit("Defina TEST_DATABASE_URL no .env: a avaliação recria o banco de testes a cada caso.")
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]  # antes de importar o app
    os.environ["RESEND_API_KEY"] = ""  # nenhum e-mail de verdade
    if args.reconferir:
        guardado = json.loads(Path(args.reconferir).read_text(encoding="utf-8"))
    else:
        if not os.getenv("ANTHROPIC_API_KEY"):
            sys.exit("Defina ANTHROPIC_API_KEY no .env: a avaliação é com o modelo de verdade (sem ele, rode o pytest).")
        if args.modelo:
            os.environ["IA_MODELO"] = args.modelo
        guardado = rodar_com_o_modelo(args.casos)
        RESPOSTAS.parent.mkdir(exist_ok=True)
        RESPOSTAS.write_text(json.dumps(guardado, ensure_ascii=False, indent=1), encoding="utf-8")

    linhas = conferir(guardado)
    Path(args.saida).write_text(relatorio(linhas, guardado, reconferido=bool(args.reconferir)), encoding="utf-8")
    acertos = sum(1 for linha in linhas if linha["ok"])
    custo = sum(linha["custo"] for linha in linhas)
    for linha in linhas:
        if not linha["ok"]:
            print(f"ERRO #{linha['caso'].numero:02d} {linha['caso'].pergunta[:60]!r} {linha['faltas']}")
    print(f"\nPlacar: {acertos} de {len(linhas)}. Custo: US$ {_num(custo, 4)}. Relatório: {args.saida}")


def rodar_com_o_modelo(numeros: list[int] | None) -> dict:
    """Cada caso numa conversa nova, no banco de testes recriado; devolve as respostas e as medidas."""
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
    client = TestClient(app)
    itens = []
    for caso in [c for c in CASOS if not numeros or c.numero in numeros]:
        limite.limpar()
        with SessionLocal() as db:
            apagar_tudo(db)
            popular(db)
            db.commit()
        inicio = time.perf_counter()
        try:
            resposta, _ = rodar(client, caso)
        except AssertionError as erro:  # a API respondeu erro (ex.: 429): o caso conta como falha
            resposta = {"texto": "", "blocos": [], "modo": "ERRO", "conversaId": None, "erro": str(erro)}
        segundos = time.perf_counter() - inicio
        custo = 0.0
        auditoria = {}
        if resposta.get("conversaId"):
            consulta = "SELECT coalesce(sum(custo_estimado), 0) FROM consumo_ia WHERE conversa_id = :c"
            custo = float(sql(consulta, c=resposta["conversaId"])[0][0])
        if resposta.get("id"):
            auditoria = sql("SELECT auditoria FROM mensagens_assistente WHERE id = :m", m=resposta["id"])[0][0] or {}
        itens.append({"numero": caso.numero, "resposta": resposta, "auditoria": auditoria, "custo": custo, "segundos": segundos})
        print(f"#{caso.numero:02d} {caso.pergunta[:60]!r} {segundos:.1f}s")
    return {"modelo": settings.IA_MODELO, "quando": datetime.now().isoformat(timespec="minutes"), "itens": itens}


def conferir(guardado: dict) -> list[dict]:
    """As conferências de hoje da bateria sobre as respostas (as da rodada ou as guardadas)."""
    from tests.bateria_lucia import CASOS

    por_numero = {caso.numero: caso for caso in CASOS}
    linhas = []
    for item in guardado["itens"]:
        caso, resposta = por_numero[item["numero"]], item["resposta"]
        faltas = [f"erro na API: {resposta['erro']}"] if resposta.get("erro") else []
        faltas += [falta for conferencia in caso.conferencias if (falta := conferencia(resposta))]
        linhas.append(
            {
                "caso": caso,
                "ok": not faltas,
                "faltas": faltas,
                "texto": resposta["texto"],
                "blocos": [b["tipo"] for b in resposta["blocos"]],
                "modo": resposta["modo"],
                "verificacao": item["auditoria"].get("verificacao"),
                "semFonte": item["auditoria"].get("semFonte"),
                "custo": item["custo"],
                "segundos": item["segundos"],
            }
        )
    return linhas


def _celula(texto: str, limite: int = 220) -> str:
    texto = " ".join((texto or "").split()).replace("|", "/")
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def _num(valor: float, casas: int) -> str:
    """Com vírgula, como no resto da documentação: 0,0138."""
    return f"{valor:.{casas}f}".replace(".", ",")


def _qtd(quantidade: int, palavra: str) -> str:
    """'1 refeita', '3 refeitas'."""
    return f"{quantidade} {palavra}" if quantidade == 1 else f"{quantidade} {palavra}s"


def relatorio(linhas: list[dict], guardado: dict, reconferido: bool = False) -> str:
    acertos = sum(1 for linha in linhas if linha["ok"])
    custo = sum(linha["custo"] for linha in linhas)
    tempos = sorted(linha["segundos"] for linha in linhas)
    p90 = tempos[min(len(tempos) - 1, int(len(tempos) * 0.9))] if tempos else 0
    verificacao = {
        situacao: sum(1 for linha in linhas if linha["verificacao"] == situacao)
        for situacao in ("CONFERIDA", "REESCRITA", "SUBSTITUIDA")
    }
    quando = datetime.fromisoformat(guardado["quando"])
    gerado = f"Rodada de {quando:%d/%m/%Y %H:%M}"
    if reconferido:
        gerado += f", conferências refeitas em {datetime.now():%d/%m/%Y %H:%M} (sem chamar o modelo de novo)"
    partes = [
        "# Avaliação da Lúcia com o Claude",
        "",
        f"{gerado}, modelo `{guardado['modelo']}`, no banco de testes (seed de demonstração), por "
        "`scripts/avaliar_lucia.py`. Os casos e o que cada resposta precisa ter estão em `tests/bateria_lucia.py` "
        "(decisão 105); a mesma bateria roda sem o Claude no pytest (`tests/test_bateria_lucia.py`).",
        "",
        f"**Placar: {acertos} de {len(linhas)}.** Custo medido: US$ {_num(custo, 4)} "
        f"(US$ {_num(custo / max(1, len(linhas)), 5)} por caso). Tempo por caso: médio "
        f"{_num(sum(tempos) / max(1, len(tempos)), 1)} s, 90% até {_num(p90, 1)} s (inclui as mensagens de antes da "
        "pergunta, quando o caso tem).",
        "",
        f"Verificador de números (decisão 101) nas respostas do modelo: {_qtd(verificacao['CONFERIDA'], 'conferida')} de "
        f"primeira, {_qtd(verificacao['REESCRITA'], 'refeita')} pelo modelo e {_qtd(verificacao['SUBSTITUIDA'], 'trocada')} "
        "pelo texto das consultas.",
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
