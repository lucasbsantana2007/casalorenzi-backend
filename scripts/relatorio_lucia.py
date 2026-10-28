"""Relatório de uma sessão de teste da Lúcia com pessoas de fora (decisão 104; roteiro em docs/teste_com_pessoas.md).
Só lê o banco: não muda nada.

    python scripts/relatorio_lucia.py --desde "2026-10-28 14:00"
    python scripts/relatorio_lucia.py --desde "2026-10-28 14:00" --ate "2026-10-28 18:00" --sem-textos

Usa o DATABASE_URL do ambiente (ou do .env). Para a sessão no site publicado, rode com a URL externa do banco do
Render. O relatório traz o que os testadores escreveram: por isso vai para relatorios/ (fora do git; o repositório é
público). Para a apresentação, --sem-textos deixa só os números.

O que mede: quantas conversas a Lúcia resolveu sem uma pessoa, as falhas (com a pergunta e a resposta), as vezes em
que ela ofereceu a equipe sozinha, os números que o verificador barrou, o "ajudou?" com os comentários, as
consultas que deram erro e o custo e o tempo das respostas.
"""

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
load_dotenv(RAIZ / ".env")

FUSO = "America/Sao_Paulo"


def _data(texto: str | None) -> datetime | None:
    if not texto:
        return None
    from src.config.settings import FUSO as TZ

    return datetime.fromisoformat(texto).replace(tzinfo=TZ)


def _curto(texto: str | None, limite: int = 200) -> str:
    texto = " ".join((texto or "").split()).replace("|", "/")
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--desde", required=True, help='Início da sessão, horário de São Paulo ("2026-10-28 14:00")')
    parser.add_argument("--ate", help="Fim da sessão (padrão: agora)")
    parser.add_argument("--sem-textos", action="store_true", help="Só os números, sem o que os testadores escreveram")
    parser.add_argument("--saida", help="Arquivo do relatório (padrão: relatorios/teste_lucia_<data>.md)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    from sqlalchemy import text

    from src.database.connection import SessionLeitura

    desde, ate = _data(args.desde), _data(args.ate) or datetime.now().astimezone()
    p = {"desde": desde, "ate": ate}
    with SessionLeitura() as db:

        def linhas(consulta: str):
            return db.execute(text(consulta), p).all()

        conversas = linhas(
            "SELECT id, status, atendimento_id, cliente_id IS NOT NULL FROM conversas_assistente "
            "WHERE tipo = 'CLIENTE' AND criada_em BETWEEN :desde AND :ate"
        )
        ids = {c[0] for c in conversas}
        mensagens = [
            m
            for m in linhas(
                "SELECT r.conversa_id, r.id, r.modo, r.auditoria, r.avaliacao, r.avaliacao_comentario, r.conteudo, "
                "q.conteudo, r.blocos FROM mensagens_assistente r JOIN conversas_assistente c ON c.id = r.conversa_id "
                "LEFT JOIN mensagens_assistente q ON q.id = r.responde_a_id "
                "WHERE c.tipo = 'CLIENTE' AND r.papel = 'ASSISTENTE' AND r.responde_a_id IS NOT NULL "
                "AND r.criada_em BETWEEN :desde AND :ate ORDER BY r.id"
            )
            if m[0] in ids
        ]
        ferramentas = linhas(
            "SELECT f.ferramenta, f.erro, count(*) FROM chamadas_ferramenta f JOIN conversas_assistente c "
            "ON c.id = f.conversa_id WHERE c.tipo = 'CLIENTE' AND NOT f.sucesso AND f.criada_em BETWEEN :desde AND :ate "
            "GROUP BY f.ferramenta, f.erro ORDER BY count(*) DESC"
        )
        consumo = linhas(
            "SELECT count(*), coalesce(sum(custo_estimado), 0), coalesce(avg(duracao_ms), 0), "
            "coalesce(percentile_cont(0.9) WITHIN GROUP (ORDER BY duracao_ms), 0) FROM consumo_ia "
            "WHERE tipo = 'CLIENTE' AND criado_em BETWEEN :desde AND :ate"
        )[0]
        motivos = linhas(
            "SELECT a.protocolo, m.conteudo FROM conversas_assistente c JOIN atendimentos a ON a.id = c.atendimento_id "
            "JOIN LATERAL (SELECT conteudo FROM mensagens WHERE atendimento_id = a.id ORDER BY id LIMIT 1) m ON true "
            "WHERE c.tipo = 'CLIENTE' AND c.criada_em BETWEEN :desde AND :ate"
        )

    texto = relatorio(args, desde, ate, conversas, mensagens, ferramentas, consumo, motivos)
    saida = Path(args.saida) if args.saida else RAIZ / "relatorios" / f"teste_lucia_{desde:%Y%m%d_%H%M}.md"
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(texto, encoding="utf-8")
    print(texto.split("\n## ")[0])
    print(f"Relatório completo: {saida}")


def relatorio(args, desde, ate, conversas, mensagens, ferramentas, consumo, motivos) -> str:
    com_texto = not args.sem_textos
    auditorias = [(m, m[3] or {}) for m in mensagens]
    modos = Counter(m[2] for m in mensagens)
    # Só conta a conversa em que o testador perguntou alguma coisa (abrir o chat e fechar não é conversa)
    conversas = [c for c in conversas if c[0] in {m[0] for m in mensagens}]
    encaminhadas = [c for c in conversas if c[2]]
    ofertas = [m for m, a in auditorias if a.get("ofereceuPessoa")]
    falhas = [m for m, a in auditorias if a.get("falhou")]
    sinais = Counter(a.get("sinalDoCliente") for _, a in auditorias if a.get("sinalDoCliente"))
    verificacao = Counter(a.get("verificacao") for _, a in auditorias if a.get("verificacao"))
    barradas = [(m, a) for m, a in auditorias if a.get("verificacao") in ("REESCRITA", "SUBSTITUIDA")]
    ajudou = sum(1 for m in mensagens if m[4] == 1)
    nao_ajudou = [m for m in mensagens if m[4] == -1]
    avaliadas = ajudou + len(nao_ajudou)
    resolvidas = len(conversas) - len(encaminhadas)
    chamadas, custo, latencia, p90 = consumo

    def pct(parte: int, total: int) -> str:
        return f"{round(100 * parte / total)}%" if total else "—"

    def num(valor, casas: int) -> str:
        return f"{float(valor):.{casas}f}".replace(".", ",")

    partes = [
        f"# Teste da Lúcia com pessoas de fora: {desde:%d/%m/%Y %H:%M} a {ate:%d/%m/%Y %H:%M}",
        "",
        f"- **Conversas:** {len(conversas)} ({sum(1 for c in conversas if c[3])} com login), {len(mensagens)} respostas "
        f"({', '.join(f'{n} {modo}' for modo, n in modos.most_common()) or 'nenhuma'}).",
        f"- **Resolvidas sem uma pessoa:** {resolvidas} de {len(conversas)} ({pct(resolvidas, len(conversas))}). "
        f"Encaminhadas para a equipe: {len(encaminhadas)}.",
        f"- **Falhas da Lúcia:** {len(falhas)} ({pct(len(falhas), len(mensagens))} das respostas). Ela ofereceu a equipe sozinha "
        f"{len(ofertas)} vezes. Sinais do cliente: {sinais.get('FRUSTRACAO', 0)} frustrações, "
        f"{sinais.get('REPETICAO', 0)} perguntas repetidas.",
        f"- **Verificador de números:** {sum(verificacao.values())} respostas conferidas, {verificacao.get('REESCRITA', 0)} "
        f"refeitas pelo modelo e {verificacao.get('SUBSTITUIDA', 0)} trocadas pelo texto das consultas.",
        f"- **Ajudou?** {avaliadas} respostas avaliadas: {ajudou} ajudou e {len(nao_ajudou)} não ajudou "
        f"({pct(ajudou, avaliadas)} positivas).",
        f"- **Custo e tempo:** {chamadas} chamadas ao modelo, US$ {num(custo, 4)} no total "
        f"(US$ {num(float(custo) / max(1, len(conversas)), 4)} por conversa); {num(float(latencia) / 1000, 1)} s por chamada "
        f"em média, 90% até {num(float(p90) / 1000, 1)} s.",
        "",
    ]
    if ferramentas:
        partes += ["## Consultas que deram erro", "", "| Ferramenta | Erro | Vezes |", "|---|---|---|"]
        partes += [f"| {f} | {_curto(e, 120)} | {n} |" for f, e, n in ferramentas]
        partes.append("")
    if not com_texto:
        return "\n".join(partes) + "\n(Sem os textos: gerado com --sem-textos.)\n"
    if nao_ajudou:
        partes += ["## “Não ajudou”", "", "| Pergunta | Resposta | Comentário |", "|---|---|---|"]
        partes += [f"| {_curto(m[7], 120)} | {_curto(m[6])} | {_curto(m[5], 160) or '—'} |" for m in nao_ajudou]
        partes.append("")
    if falhas:
        partes += ["## Falhas", "", "| Pergunta | Resposta |", "|---|---|"]
        partes += [f"| {_curto(m[7], 120)} | {_curto(m[6])} |" for m in falhas]
        partes.append("")
    if barradas:
        partes += [
            "## Números que o verificador barrou",
            "",
            "| Pergunta | O modelo tinha escrito | Sem fonte | Saiu |",
            "|---|---|---|---|",
        ]
        for m, a in barradas:
            sem_fonte = ", ".join(a.get("semFonte") or [])
            partes.append(f"| {_curto(m[7], 100)} | {_curto(a.get('textoModelo'), 160)} | {sem_fonte} | {_curto(m[6], 160)} |")
        partes.append("")
    if motivos:
        partes += ["## Encaminhadas para a equipe", ""]
        for protocolo, conteudo in motivos:
            # O resumo começa com "Solicitação aberta pela Lúcia..." e o motivo vem na linha seguinte
            resumo = conteudo.splitlines()
            partes.append(f"- {protocolo}: {_curto(resumo[1] if len(resumo) > 1 else conteudo, 200)}")
        partes.append("")
    return "\n".join(partes) + "\n"


if __name__ == "__main__":
    main()
