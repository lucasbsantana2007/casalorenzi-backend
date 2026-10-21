"""Gera o diagrama do banco (docs/diagrama_banco.html) a partir dos models.

Com --comparar-com, marca o que é novo ou mudou em relação a um banco numa versão anterior (ex.: um banco
em e685fb1136f9 mostra a união com a Vulto). Sem ele, desenha o banco sem marcas. Rode da raiz do backend:

    python scripts/diagrama_banco/gerar.py --comparar-com postgresql+psycopg://...
"""

import argparse
import html
import inspect as pyinspect
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint, create_engine, inspect
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import models  # noqa: E402, F401
from src.database.connection import Base  # noqa: E402

PASTA = Path(__file__).resolve().parent
args = argparse.ArgumentParser(description="Gera o diagrama do banco a partir dos models.")
args.add_argument("--comparar-com", help="URL de um banco numa versão anterior, para marcar o que mudou")
args.add_argument("--saida", default=str(PASTA.parents[1] / "docs" / "diagrama_banco.html"))
args = args.parse_args()
DIALETO = postgresql.dialect()
ins = inspect(create_engine(args.comparar_com)) if args.comparar_com else None
ANTIGAS = (set(ins.get_table_names()) if ins else set(Base.metadata.tables)) - {"alembic_version"}
esc = html.escape


def colunas_antigas(nome: str) -> list[dict]:
    if ins:
        return ins.get_columns(nome)
    return [{"name": c.name, "nullable": c.nullable, "type": c.type} for c in Base.metadata.tables[nome].columns]


def checks_antigos(nome: str) -> dict[str, str]:
    if ins:
        return {c["name"]: c["sqltext"] for c in ins.get_check_constraints(nome)}
    tabela = Base.metadata.tables[nome]
    return {c.name: str(c.sqltext) for c in tabela.constraints if isinstance(c, CheckConstraint)}


def tipo_curto(t) -> str:
    s = t.compile(dialect=DIALETO)
    for a, b in (("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"), ("INTEGER", "INT"), ("BOOLEAN", "BOOL"), (", ", ",")):
        s = s.replace(a, b)
    return s


# ---------- textos dos models (docstring da classe e comentários acima de cada coluna) ----------
CLASSES = {mp.class_.__tablename__: mp.class_ for mp in Base.registry.mappers}
SEM_DOC = {
    "categorias": "Categoria da peça (Camisaria, Calças, Tricô...). Uma lista só para as duas marcas.",
    "transferencias": (
        "Envio de peças entre lojas e o CD: SOLICITADA → EM_TRANSITO (baixa na origem) → CONCLUIDA (entra no destino)."
    ),
    "tipos_solicitacao": "Assunto do atendimento (troca, devolução, entrega...). Os inativos não aparecem para o cliente.",
}


def doc_da_tabela(nome: str) -> str:
    doc = pyinspect.getdoc(CLASSES[nome]) or ""
    if not doc or doc == pyinspect.getdoc(Base):
        return SEM_DOC.get(nome, "")
    return " ".join(doc.split("\n\n")[0].split())


def notas_das_colunas(nome: str) -> dict[str, str]:
    linhas = pyinspect.getsource(CLASSES[nome]).splitlines()
    notas, comentario = {}, []
    for linha in linhas:
        s = linha.strip()
        if s.startswith("#"):
            comentario.append(s.lstrip("# ").strip())
            continue
        achou = re.match(r"(\w+): Mapped\[", s)
        if achou and comentario:
            notas[achou.group(1)] = " ".join(comentario)
        comentario = []
    return notas


# ---------- regras (checks) em palavras ----------
REGRAS = {
    "ck_pedidos_total": "total = subtotal − desconto + frete",
    "ck_pedidos_desconto": "desconto entre zero e o subtotal",
    "ck_itens_pedido_quantidade": "quantidade maior que zero",
    "ck_itens_pedido_preco": "preço não negativo",
    "ck_devolucoes_item_do_pedido": "item só junto com o pedido dele",
    "ck_estoques_quantidade": "estoque e mínimo nunca negativos",
    "ck_movimentacoes_saldo": "saldo resultante nunca negativo",
    "ck_movimentacoes_custo": "custo unitário não negativo",
    "ck_variacoes_preco": "preço próprio não negativo",
    "ck_variacoes_ean": "EAN com 13 dígitos",
    "ck_clientes_identificacao": "todo cliente tem CPF ou e-mail (fora a conta excluída)",
    "ck_atendimentos_cliente_ou_contato": "tem o cliente ou, ao menos, o contato que ele usou",
    "ck_movimentos_pontos_sinal": "crédito e saldo inicial entram; resgate, estorno e vencimento saem; ajuste nos dois sentidos",
    "ck_movimentos_pontos_saldo": "saldo de pontos nunca negativo",
    "ck_movimentos_pontos_valor": "desconto do resgate não negativo",
}


def valores(sql: str) -> list[str]:
    return re.findall(r"'([^']*)'", sql)


def regras_da_tabela(nome: str) -> list[dict]:
    tabela = Base.metadata.tables[nome]
    antigas = checks_antigos(nome) if nome in ANTIGAS else {}
    saida = []
    for ck in (c for c in tabela.constraints if isinstance(c, CheckConstraint)):
        sql = str(ck.sqltext)
        texto = REGRAS.get(ck.name)
        lista = valores(sql)
        if texto is None and " IN (" in sql:
            coluna = sql.split(" IN (")[0].split()[-1]
            texto = f"{coluna}: " + ", ".join(lista)
        texto = texto or sql
        if ck.name not in antigas:
            estado, extra = ("nova" if nome in ANTIGAS else "igual"), ""
        else:
            novos = [v for v in lista if v not in valores(antigas[ck.name])]
            estado, extra = ("ampliada", "entrou " + ", ".join(novos)) if novos else ("igual", "")
        saida.append({"nome": ck.name, "texto": texto, "estado": estado, "extra": extra})
    return sorted(saida, key=lambda r: ("nova", "ampliada", "igual").index(r["estado"]))


# ---------- tabelas, colunas e o que mudou ----------
def unicos_antigos(nome: str) -> set[str]:
    if not ins:
        return unicos_novos(Base.metadata.tables[nome])
    u = {c["column_names"][0] for c in ins.get_unique_constraints(nome) if len(c["column_names"]) == 1}
    return u | {i["column_names"][0] for i in ins.get_indexes(nome) if i["unique"] and len(i["column_names"]) == 1}


def unicos_novos(tabela) -> set[str]:
    u = {c.name for c in tabela.columns if c.unique}
    u |= {i.columns[0].name for i in tabela.indexes if i.unique and len(i.columns) == 1}
    return u | {list(c.columns)[0].name for c in tabela.constraints if isinstance(c, UniqueConstraint) and len(c.columns) == 1}


TABELAS = {}
for nome, tabela in Base.metadata.tables.items():
    notas = notas_das_colunas(nome)
    nova = nome not in ANTIGAS
    antigas = {c["name"]: c for c in colunas_antigas(nome)} if not nova else {}
    u_ant, u_nov = (unicos_antigos(nome), unicos_novos(tabela)) if not nova else (set(), set())
    colunas = []
    for col in tabela.columns:
        mudancas = []
        if nova:
            estado = "igual"  # a tabela inteira é nova: as colunas não ganham marca própria
        elif col.name not in antigas:
            estado = "nova"
        else:
            velha = antigas[col.name]
            if velha["nullable"] != col.nullable:
                mudancas.append("agora opcional" if col.nullable else "agora obrigatória")
            if tipo_curto(velha["type"]) != tipo_curto(col.type):
                mudancas.append(f"era {tipo_curto(velha['type'])}")
            if (col.name in u_ant) != (col.name in u_nov):
                mudancas.append("deixou de ser única" if col.name in u_ant else "agora única")
            estado = "mudou" if mudancas else "igual"
        fk = next(iter(col.foreign_keys), None)
        colunas.append(
            {
                "nome": col.name,
                "tipo": tipo_curto(col.type),
                "pk": col.primary_key,
                "fk": f"{fk.column.table.name}.{fk.column.name}" if fk else None,
                "unica": col.name in unicos_novos(tabela),
                "opcional": bool(col.nullable) and not col.primary_key,
                "estado": estado,
                "mudancas": mudancas,
                "nota": notas.get(col.name, ""),
            }
        )
    regras = regras_da_tabela(nome)
    if nova:
        estado = "nova"
    elif any(c["estado"] != "igual" for c in colunas) or any(r["estado"] != "igual" for r in regras):
        estado = "alterada"
    else:
        estado = "igual"
    removidas = sorted(set(antigas) - {c.name for c in tabela.columns})
    TABELAS[nome] = {
        "nome": nome,
        "estado": estado,
        "doc": doc_da_tabela(nome),
        "colunas": colunas,
        "regras": regras,
        "removidas": removidas,
    }

APAGADAS = sorted(ANTIGAS - set(TABELAS))

# ---------- layout: uma coluna por assunto ----------
GRUPOS = [
    ("Catálogo", ["categorias", "fornecedores", "produtos", "imagens_produto", "variacoes"]),
    ("Estoque", ["estoques", "movimentacoes", "transferencias"]),
    ("Vendas", ["pedidos", "itens_pedido", "pagamentos", "eventos_pedido", "devolucoes"]),
    ("Lojas, equipe e clientes", ["lojas", "usuarios", "clientes", "tokens_senha", "log_acoes"]),
    ("Vulto+ e atendimento", ["movimentos_pontos", "atendimentos", "mensagens", "anexos", "tipos_solicitacao"]),
    ("Frete e migração", ["config_frete", "frete_regioes", "decisoes_migracao", "de_para"]),
]
assert sorted(n for _, ns in GRUPOS for n in ns) == sorted(TABELAS), set(TABELAS) ^ {n for _, ns in GRUPOS for n in ns}

CH, CH_H, ROW, HEAD, GUT, TOPO, GAP, MARG = 6.6, 7.4, 19, 28, 150, 74, 40, 36
col_x, col_w, pos = [], [], {}
x = MARG
for _, nomes in GRUPOS:
    largura = max(
        max(len(c["nome"]) + len(c["tipo"]) for n in nomes for c in TABELAS[n]["colunas"]) * CH + 70,
        max(len(n) * CH_H + 110 for n in nomes),
    )
    largura = round(largura)
    col_x.append(x)
    col_w.append(largura)
    y = TOPO
    for n in nomes:
        altura = HEAD + ROW * len(TABELAS[n]["colunas"]) + 6
        pos[n] = {"c": len(col_x) - 1, "x": x, "y": y, "w": largura, "h": altura}
        y += altura + GAP
    x += largura + GUT
W = x - GUT + GUT + MARG  # a última calha também serve para as ligações da última coluna
H = max(p["y"] + p["h"] for p in pos.values()) + MARG


def y_linha(nome: str, coluna: str) -> float:
    i = next(k for k, c in enumerate(TABELAS[nome]["colunas"]) if c["nome"] == coluna)
    return pos[nome]["y"] + HEAD + i * ROW + ROW / 2


# ---------- ligações (chaves estrangeiras) com rotas em calhas ----------
LIGACOES = []
for nome, t in TABELAS.items():
    for c in t["colunas"]:
        if not c["fk"]:
            continue
        alvo, alvo_col = c["fk"].split(".")
        a, b = pos[nome], pos[alvo]
        ya, yb = y_linha(nome, c["nome"]), y_linha(alvo, alvo_col)
        if a["c"] < b["c"]:
            calha, sai, chega = a["c"], ("R", a["x"] + a["w"]), ("L", b["x"])
        elif a["c"] > b["c"]:
            calha, sai, chega = a["c"] - 1, ("L", a["x"]), ("R", b["x"] + b["w"])
        else:
            calha, sai, chega = a["c"], ("R", a["x"] + a["w"]), ("R", b["x"] + b["w"])
        estado = "nova" if c["estado"] == "nova" else ("mudou" if c["mudancas"] else "igual")
        LIGACOES.append(
            {
                "id": f"{nome}.{c['nome']}",
                "de": nome,
                "para": alvo,
                "calha": calha,
                "ya": ya,
                "yb": yb,
                "sai": sai,
                "chega": chega,
                "opcional": c["opcional"],
                "estado": estado,
            }
        )

# trilhas: cada trecho vertical ganha a sua, sem sobrepor outro trecho na mesma calha
por_calha = defaultdict(list)
for lig in LIGACOES:
    por_calha[lig["calha"]].append(lig)
for calha, ligs in por_calha.items():
    fins = []
    for lig in sorted(ligs, key=lambda g: (min(g["ya"], g["yb"]), max(g["ya"], g["yb"]))):
        y0, y1 = min(lig["ya"], lig["yb"]), max(lig["ya"], lig["yb"])
        k = next((i for i, fim in enumerate(fins) if fim + 10 < y0), None)
        if k is None:
            fins.append(y1)
            k = len(fins) - 1
        else:
            fins[k] = y1
        lig["trilha"] = k
    n = len(fins)
    x0 = col_x[calha] + col_w[calha]
    for lig in ligs:
        lig["x"] = round(x0 + (lig["trilha"] + 1) * GUT / (n + 1), 1)


def caminho(lig) -> str:
    (lado_a, xa), (lado_b, xb), ya, yb, xm = lig["sai"], lig["chega"], lig["ya"], lig["yb"], lig["x"]
    da = 1 if lado_a == "R" else -1
    db = 1 if lado_b == "R" else -1
    linha = f"M{xa},{ya} H{xm} V{yb} H{xb}"
    # pé de galinha (muitos) no lado da chave estrangeira; traço (um) no lado referenciado
    pe = f"M{xa + 12 * da},{ya} L{xa},{ya - 5} M{xa + 12 * da},{ya} L{xa},{ya + 5}"
    traco = f"M{xb + 8 * db},{yb - 5} V{yb + 5}"
    return linha, f"{pe} {traco}"


# ---------- SVG ----------
partes = [
    f'<svg id="mapa" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
    f'aria-label="Diagrama do banco unificado: {len(TABELAS)} tabelas, ligações por chave estrangeira">'
]
for i, (titulo, _) in enumerate(GRUPOS):
    partes.append(f'<text class="grupo" x="{col_x[i]}" y="{TOPO - 30}">{esc(titulo.upper())}</text>')
partes.append('<g id="ligacoes">')
for lig in LIGACOES:
    classes = f"rel {lig['estado']}" + (" opcional" if lig["opcional"] else "")
    rotulo = f"{lig['id']} → {lig['para']}" + (" (opcional)" if lig["opcional"] else "")
    partes.append(
        f'<g class="{classes}" data-e="{lig["id"]}" data-a="{lig["de"]}" data-b="{lig["para"]}">'
        f'<title>{esc(rotulo)}</title><path class="l" d="{caminho(lig)[0]}"/><path class="m" d="{caminho(lig)[1]}"/></g>'
    )
partes.append('</g><g id="tabelas">')
ROTULO = {"nova": "NOVA", "alterada": "ALTERADA", "igual": ""}
for nome, t in TABELAS.items():
    p = pos[nome]
    x, y, w = p["x"], p["y"], p["w"]
    partes.append(
        f'<g class="tab {t["estado"]}" data-t="{nome}" tabindex="0" role="button" aria-label="Tabela {nome}">'
        f'<rect class="corpo" x="{x}" y="{y}" width="{w}" height="{p["h"]}" rx="6"/>'
        f'<path class="cab" d="M{x},{y + 6} a6,6 0 0 1 6,-6 h{w - 12} a6,6 0 0 1 6,6 v{HEAD - 6} h-{w} z"/>'
        f'<text class="nome-tab" x="{x + 10}" y="{y + 18.5}">{esc(nome)}</text>'
    )
    if ROTULO[t["estado"]]:
        partes.append(f'<text class="selo" x="{x + w - 10}" y="{y + 18}" text-anchor="end">{ROTULO[t["estado"]]}</text>')
    for k, c in enumerate(t["colunas"]):
        yl = y + HEAD + k * ROW
        cls = f"lin {c['estado']}"
        partes.append(f'<g class="{cls}" data-c="{c["nome"]}">')
        if c["estado"] != "igual":
            partes.append(f'<rect class="fundo" x="{x + 1}" y="{yl}" width="{w - 2}" height="{ROW}"/>')
            partes.append(f'<rect class="marca" x="{x + 1}" y="{yl + 3}" width="3" height="{ROW - 6}"/>')
        chave = "PK" if c["pk"] else ("FK" if c["fk"] else ("UQ" if c["unica"] else ""))
        if chave:
            partes.append(f'<text class="chave" x="{x + 10}" y="{yl + 13}">{chave}</text>')
        bolinha = "vazia" if c["opcional"] else "cheia"
        partes.append(f'<circle class="ponto {bolinha}" cx="{x + 32}" cy="{yl + ROW / 2}" r="3"/>')
        partes.append(f'<text class="col" x="{x + 41}" y="{yl + 13}">{esc(c["nome"])}</text>')
        partes.append(f'<text class="tipo" x="{x + w - 10}" y="{yl + 13}" text-anchor="end">{esc(c["tipo"])}</text>')
        partes.append("</g>")
    partes.append("</g>")
partes.append("</g></svg>")
SVG = "".join(partes)

# ---------- resumo ----------
cont = {e: sum(1 for t in TABELAS.values() if t["estado"] == e) for e in ("nova", "alterada", "igual")}
colunas_novas = sum(1 for t in TABELAS.values() if t["estado"] == "alterada" for c in t["colunas"] if c["estado"] == "nova")
colunas_mudaram = sum(1 for t in TABELAS.values() for c in t["colunas"] if c["estado"] == "mudou")
regras_novas = sum(1 for t in TABELAS.values() for r in t["regras"] if r["estado"] in ("nova", "ampliada"))
regras_novas += sum(len(t["regras"]) for t in TABELAS.values() if t["estado"] == "nova")
DADOS = {"tabelas": TABELAS, "ligacoes": [{k: g[k] for k in ("id", "de", "para", "estado", "opcional")} for g in LIGACOES]}
RESUMO = {
    "total": len(TABELAS),
    "antes": len(ANTIGAS),
    "novas": cont["nova"],
    "alteradas": cont["alterada"],
    "iguais": cont["igual"],
    "apagadas": APAGADAS,
    "colunas_novas": colunas_novas,
    "colunas_mudaram": colunas_mudaram,
    "regras": regras_novas,
    "ligacoes": len(LIGACOES),
    "W": W,
}

modelo = (PASTA / "modelo.html").read_text(encoding="utf-8")
pagina = (
    modelo.replace("<!--SVG-->", SVG)
    .replace("/*DADOS*/null", json.dumps(DADOS, ensure_ascii=False))
    .replace("/*RESUMO*/null", json.dumps(RESUMO, ensure_ascii=False))
)
for chave, valor in RESUMO.items():
    pagina = pagina.replace("{{" + chave + "}}", str(valor if not isinstance(valor, list) else len(valor)))
# Documento completo, para abrir direto no navegador (o que vem antes do conteúdo vai para o <head>)
cabeca, corpo = pagina.split('<div class="pagina">', 1)
documento = (
    '<!doctype html>\n<html lang="pt-BR">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    f'{cabeca}</head>\n<body>\n<div class="pagina">{corpo}</body>\n</html>\n'
)
Path(args.saida).write_text(documento, encoding="utf-8")
print(f"{args.saida}: {RESUMO['total']} tabelas ({RESUMO['novas']} novas, {RESUMO['alteradas']} alteradas)")
