"""Ferramentas do copiloto gerencial: vendas, estoque, transferências, Lupe+ e alertas, só leitura.

Cada uma exige o módulo que já dá acesso ao assunto no painel (src/entities/papeis.py): vendas e Lupe+ pedem
"financeiro" (só o Administrador), estoque pede "estoque", sugestões de transferência pedem "transferencias".
A marca vem do token: quem é de uma marca só vê a dela (pedir a outra responde SEM_PERMISSAO); o Administrador
do grupo vê as duas ou a escolhida no seletor do painel. Os números saem de src/use_cases/analises.py, que
reaproveita o financeiro, o estoque e o Lupe+ oficiais. As consultas rodam numa transação READ ONLY.
"""

from typing import Literal

from pydantic import Field
from sqlalchemy.orm import Session

from src.entities.assistente import DEFINICOES, MODULO_DO_ALERTA
from src.entities.marca import na_marca
from src.entities.papeis import pode_acessar
from src.entities.pedido import CANAIS
from src.entities.periodo import PERIODO_PADRAO, PERIODOS, Periodo, resolver
from src.repositories import alerta_repository, analise_repository, cadastro_repository
from src.use_cases import analises
from src.use_cases.assistente.ferramentas import Contexto, Entrada, FalhaFerramenta, Ferramenta, Resultado
from src.use_cases.assistente.formatacao import (
    bloco_fonte,
    bloco_grafico,
    bloco_indicadores,
    bloco_tabela,
    brl,
    data,
    numero,
    pct,
)
from src.utils.datas import hoje, ler_data

NomePeriodo = Literal[PERIODOS]  # type: ignore[valid-type]
Marca = Literal["LORENZI", "VULTO"]
Canal = Literal[CANAIS]  # type: ignore[valid-type]
NOME_MARCA = {"LORENZI": "Casa Lorenzi", "VULTO": "Vulto", None: "Casa Lorenzi e Vulto"}
DESCRICAO_PERIODO = (
    "Período: hoje, ontem, semana_atual (segunda até hoje), semana_passada, mes_atual, mes_passado, ultimos_7_dias, "
    "ultimos_30_dias, ultimos_90_dias, ano_atual, ano_passado ou personalizado (com de e ate)."
)


class ComPeriodo(Entrada):
    periodo: NomePeriodo = Field(PERIODO_PADRAO, description=DESCRICAO_PERIODO)  # type: ignore[valid-type]
    de: str | None = Field(None, description="Data inicial AAAA-MM-DD (só com periodo=personalizado).")
    ate: str | None = Field(None, description="Data final AAAA-MM-DD (só com periodo=personalizado).")


class ComEscopo(Entrada):
    marca: Marca | None = Field(None, description="Só uma marca. Vazio: todas as que a pessoa pode ver.")
    loja_id: int | None = Field(None, description="Só uma loja (id da lista de lojas do contexto).")


def _periodo(entrada: ComPeriodo) -> Periodo:
    return resolver(entrada.periodo, hoje(), ler_data(entrada.de, "de"), ler_data(entrada.ate, "ate"))


def _escopo(
    db: Session, ctx: Contexto, marca: str | None, loja_id: int | None
) -> tuple[str | None, list[int] | None, str | None]:
    """(marca efetiva, lojas, nome da loja) dentro do que o token permite."""
    if marca and ctx.marca_escopo and marca != ctx.marca_escopo:
        raise FalhaFerramenta(f"SEM_PERMISSAO: o seu acesso é só da {NOME_MARCA[ctx.marca_escopo]}.")
    efetiva = marca or ctx.marca_escopo
    if loja_id is None:
        return efetiva, None, None
    loja = cadastro_repository.loja(db, loja_id)
    if loja is None or not na_marca(efetiva, loja.marca):
        raise FalhaFerramenta("LOJA_NAO_ENCONTRADA: use o id de uma loja da lista do contexto.")
    return efetiva, [loja.id], loja.nome


def _filtros(marca: str | None, loja: str | None = None, canal: str | None = None, extra: list[str] | None = None) -> list[str]:
    filtros = [f"Marca: {NOME_MARCA[marca]}"]
    if loja:
        filtros.append(f"Loja: {loja}")
    if canal:
        filtros.append(f"Canal: {canal}")
    return filtros + (extra or [])


def _dados_ate(db: Session, marca: str | None):
    return analises.dados_ate(db, marca)


def _sem_vendas(db: Session, marca: str | None) -> str:
    ultimo = _dados_ate(db, marca)
    return (
        f"Nenhuma venda registrada no período. Os dados de vendas vão até {data(ultimo)}."
        if ultimo
        else "Ainda não há vendas registradas."
    )


# ---------- Vendas ----------


class Faturamento(ComPeriodo, ComEscopo):
    canal: Canal | None = None  # type: ignore[valid-type]
    comparar: Literal["nenhum", "periodo_anterior", "ano_anterior"] = "nenhum"
    agrupar_por: Literal["nenhum", "marca", "loja", "canal", "categoria", "dia", "semana", "mes"] = Field(
        "nenhum", description="Quebra do resultado: por marca, loja, canal, categoria ou ao longo do tempo."
    )


def consultar_faturamento(db: Session, ctx: Contexto, entrada: Faturamento) -> Resultado:
    periodo = _periodo(entrada)
    marca, lojas, nome_loja = _escopo(db, ctx, entrada.marca, entrada.loja_id)
    comparar = {"nenhum": "nenhum", "periodo_anterior": "anterior", "ano_anterior": "ano"}[entrada.comparar]
    if entrada.agrupar_por in ("dia", "semana", "mes"):
        agrupar = entrada.agrupar_por
    else:
        agrupar = "dia" if periodo.dias <= 62 else ("semana" if periodo.dias <= 180 else "mes")
    r = analises.faturamento(db, periodo, marca=marca, lojas=lojas, canal=entrada.canal, comparar=comparar, agrupar=agrupar)
    filtros = _filtros(marca, nome_loja, entrada.canal)

    indicadores = [
        ("Faturamento", r["faturamento"], "moeda"),
        ("Receita de vendas", r["receitaBruta"], "moeda"),
        ("Devoluções", r["devolucoes"], "moeda"),
        ("Pedidos", r["pedidos"], "numero"),
        ("Ticket médio", r["ticketMedio"], "moeda"),
        ("Pedidos cancelados", r["cancelados"], "numero"),
    ]
    dados = {
        "periodo": periodo.rotulo,
        "filtros": filtros,
        "faturamento": brl(r["faturamento"]),
        "receitaDeVendas": brl(r["receitaBruta"]),
        "devolucoes": brl(r["devolucoes"]),
        "pedidos": numero(r["pedidos"]),
        "pecas": numero(r["pecas"]),
        "ticketMedio": brl(r["ticketMedio"]),
        "pedidosCancelados": numero(r["cancelados"]),
        "definicao": DEFINICOES["faturamento"],
    }
    if r["anterior"]:
        rotulo = "período anterior" if comparar == "anterior" else "mesmo período do ano anterior"
        dados["comparacao"] = {
            "com": rotulo,
            "faturamentoAnterior": brl(r["anterior"]["faturamento"]),
            "variacao": pct(r["variacao"]) if r["variacao"] is not None else "sem base de comparação",
        }
        indicadores.append((f"Variação vs {rotulo}", r["variacao"], "percentual"))
    if r["pedidos"] == 0:
        dados["observacao"] = _sem_vendas(db, marca)

    blocos = [bloco_indicadores(indicadores, f"Vendas · {periodo.rotulo}")]
    agrupamento = entrada.agrupar_por
    if agrupamento == "marca":
        linhas = analises.faturamento_por_marca(db, periodo, marca=marca, lojas=lojas, canal=entrada.canal)
        linhas = [{**linha, "nome": NOME_MARCA[linha["marca"]]} for linha in linhas]
        dados["porMarca"] = [
            {"marca": linha["nome"], "faturamento": brl(linha["faturamento"]), "pedidos": numero(linha["pedidos"])}
            for linha in linhas
        ]
        blocos.append(_tabela_vendas("Faturamento por marca", "nome", "Marca", linhas))
        blocos.append(_barras("Faturamento por marca", "nome", linhas))
    elif agrupamento == "loja":
        linhas = sorted(
            (linha for linha in r["porLoja"] if linha["pedidos"] or linha["devolucoes"]), key=lambda linha: -linha["faturamento"]
        )
        dados["porLoja"] = [
            {
                "loja": linha["loja"],
                "tipo": "CD (expede o online)" if linha["tipo"] == "CD" else "loja física",
                "faturamento": brl(linha["faturamento"]),
                "pedidos": numero(linha["pedidos"]),
            }
            for linha in linhas
        ]
        blocos.append(_tabela_vendas("Faturamento por loja (online conta na loja que expede)", "loja", "Loja", linhas))
        blocos.append(_barras("Faturamento por loja", "loja", linhas))
    elif agrupamento == "canal":
        linhas = sorted(r["porCanal"], key=lambda linha: -linha["faturamento"])
        dados["porCanal"] = [
            {"canal": linha["canal"], "faturamento": brl(linha["faturamento"]), "pedidos": numero(linha["pedidos"])}
            for linha in linhas
        ]
        blocos.append(_tabela_vendas("Faturamento por canal", "canal", "Canal", linhas))
        blocos.append(_barras("Faturamento por canal", "canal", linhas))
    elif agrupamento == "categoria":
        linhas = r["porCategoria"][:12]
        dados["porCategoria"] = [
            {"categoria": linha["categoria"], "receitaEmItens": brl(linha["receitaItens"])} for linha in linhas
        ]
        dados["definicaoCategoria"] = DEFINICOES["receita_categoria"]
        blocos.append(
            bloco_tabela(
                "Receita em itens por categoria",
                [("categoria", "Categoria", "texto"), ("receitaItens", "Receita em itens", "moeda")],
                linhas,
            )
        )
        blocos.append(
            bloco_grafico(
                "Receita em itens por categoria",
                "barras",
                "categoria",
                [{"chave": "receitaItens", "rotulo": "Receita em itens"}],
                [{"x": linha["categoria"], "receitaItens": linha["receitaItens"]} for linha in linhas],
            )
        )
    if periodo.dias > 1 and r["pedidos"]:
        rotulo = {"dia": "dia", "semana": "semana", "mes": "mês"}[agrupar]
        pontos = [{"x": ponto["data"], "receita": ponto["valor"]} for ponto in r["serie"]]
        blocos.append(
            bloco_grafico(
                f"Receita de vendas por {rotulo}", "linha", "data", [{"chave": "receita", "rotulo": "Receita de vendas"}], pontos
            )
        )
    blocos.append(
        bloco_fonte(
            "consultar_faturamento (regra do financeiro)",
            periodo.rotulo,
            filtros,
            DEFINICOES["faturamento"],
            _dados_ate(db, marca),
        )
    )
    return Resultado(dados=dados, blocos=blocos, texto=_texto_faturamento(dados, periodo))


def _tabela_vendas(titulo: str, chave: str, rotulo: str, linhas: list[dict]) -> dict:
    colunas = [
        (chave, rotulo, "texto"),
        ("faturamento", "Faturamento", "moeda"),
        ("receitaBruta", "Receita de vendas", "moeda"),
        ("devolucoes", "Devoluções", "moeda"),
        ("pedidos", "Pedidos", "numero"),
    ]
    return bloco_tabela(titulo, colunas, linhas)


def _barras(titulo: str, chave: str, linhas: list[dict]) -> dict:
    return bloco_grafico(
        titulo,
        "barras",
        chave,
        [{"chave": "faturamento", "rotulo": "Faturamento"}],
        [{"x": linha[chave], "faturamento": linha["faturamento"]} for linha in linhas],
    )


def _texto_faturamento(dados: dict, periodo: Periodo) -> str:
    texto = f"Faturamento {periodo.frase}: {dados['faturamento']} ({dados['pedidos']} pedidos, ticket médio de {dados['ticketMedio']})."
    if dados.get("comparacao"):
        texto += f" Em relação ao {dados['comparacao']['com']}: {dados['comparacao']['variacao']}."
    if dados.get("porMarca"):
        texto += " Por marca: " + "; ".join(f"{linha['marca']} {linha['faturamento']}" for linha in dados["porMarca"]) + "."
    if dados.get("porLoja"):
        primeira = dados["porLoja"][0]
        fisicas = [linha for linha in dados["porLoja"] if linha["tipo"] == "loja física"]
        if primeira["tipo"] == "loja física":
            texto += f" A loja com maior faturamento foi a {primeira['loja']} ({primeira['faturamento']})."
        else:
            texto += f" O maior faturamento foi do {primeira['loja']} ({primeira['faturamento']}), que expede as vendas online."
            if fisicas:
                texto += f" Entre as lojas físicas, a maior foi a {fisicas[0]['loja']} ({fisicas[0]['faturamento']})."
    if dados.get("porCanal"):
        texto += " Por canal: " + "; ".join(f"{linha['canal']} {linha['faturamento']}" for linha in dados["porCanal"]) + "."
    if dados.get("observacao"):
        texto += f" {dados['observacao']}"
    return texto


class MaisVendidos(ComPeriodo, ComEscopo):
    canal: Canal | None = None  # type: ignore[valid-type]
    categoria: str | None = Field(None, max_length=60, description="Nome exato de uma categoria da lista do contexto.")
    ordenar_por: Literal["pecas", "valor"] = "pecas"
    limite: int = Field(10, ge=1, le=20)


def consultar_mais_vendidos(db: Session, ctx: Contexto, entrada: MaisVendidos) -> Resultado:
    periodo = _periodo(entrada)
    marca, lojas, nome_loja = _escopo(db, ctx, entrada.marca, entrada.loja_id)
    if entrada.categoria and entrada.categoria not in cadastro_repository.nomes_categorias(db):
        raise FalhaFerramenta("CATEGORIA_NAO_ENCONTRADA: use o nome exato de uma categoria da lista do contexto.")
    linhas = analises.mais_vendidos(
        db,
        periodo,
        marca=marca,
        lojas=lojas,
        canal=entrada.canal,
        categoria=entrada.categoria,
        ordenar_por=entrada.ordenar_por,
        limite=entrada.limite,
    )
    filtros = _filtros(marca, nome_loja, entrada.canal, [f"Categoria: {entrada.categoria}"] if entrada.categoria else None)
    ordem = "valor" if entrada.ordenar_por == "valor" else "peças"
    dados = {
        "periodo": periodo.rotulo,
        "filtros": filtros,
        "ordenadoPor": ordem,
        "produtos": [
            {
                "posicao": i,
                "produto": linha["produto"],
                "marca": NOME_MARCA[linha["marca"]],
                "pecas": numero(linha["pecas"]),
                "valor": brl(linha["valor"]),
            }
            for i, linha in enumerate(linhas, start=1)
        ],
        "definicao": DEFINICOES["mais_vendidos"],
    }
    if not linhas:
        dados["observacao"] = _sem_vendas(db, marca)
    for i, linha in enumerate(linhas, start=1):
        linha["posicao"] = i
        linha["nomeMarca"] = NOME_MARCA[linha["marca"]]
    colunas = [
        ("posicao", "#", "numero"),
        ("produto", "Produto", "texto"),
        ("nomeMarca", "Marca", "texto"),
        ("categoria", "Categoria", "texto"),
        ("pecas", "Peças", "numero"),
        ("valor", "Valor em itens", "moeda"),
    ]
    blocos = []
    if linhas:
        blocos.append(bloco_tabela(f"Mais vendidos por {ordem} · {periodo.rotulo}", colunas, linhas))
        chave = "valor" if entrada.ordenar_por == "valor" else "pecas"
        blocos.append(
            bloco_grafico(
                "Mais vendidos",
                "barras",
                "produto",
                [{"chave": chave, "rotulo": "Valor" if chave == "valor" else "Peças"}],
                [{"x": linha["produto"], chave: linha[chave]} for linha in linhas],
                "moeda" if chave == "valor" else "numero",
            )
        )
    blocos.append(
        bloco_fonte("consultar_mais_vendidos", periodo.rotulo, filtros, DEFINICOES["mais_vendidos"], _dados_ate(db, marca))
    )
    if linhas:
        top = dados["produtos"][:3]
        texto = (
            f"Mais vendidos {periodo.frase} (por {ordem}): "
            + "; ".join(f"{p['posicao']}º {p['produto']} ({p['pecas']} peças, {p['valor']})" for p in top)
            + "."
        )
    else:
        texto = dados["observacao"]
    return Resultado(dados=dados, blocos=blocos, texto=texto)


class Cancelamentos(ComPeriodo, ComEscopo):
    pass


def consultar_cancelamentos(db: Session, ctx: Contexto, entrada: Cancelamentos) -> Resultado:
    periodo = _periodo(entrada)
    marca, lojas, nome_loja = _escopo(db, ctx, entrada.marca, entrada.loja_id)
    r = analises.cancelamentos(db, periodo, marca=marca, lojas=lojas)
    filtros = _filtros(marca, nome_loja)
    dados = {
        "periodo": periodo.rotulo,
        "filtros": filtros,
        "cancelados": numero(r["quantidade"]),
        "valorCancelado": brl(r["valor"]),
        "pedidosDeVendaNoPeriodo": numero(r["pedidosNoPeriodo"]),
        "taxaDeCancelamento": pct(r["taxa"]),
        "porMotivo": [
            {"motivo": linha["motivo"], "quantidade": numero(linha["quantidade"]), "valor": brl(linha["valor"])}
            for linha in r["porMotivo"]
        ],
        "definicao": DEFINICOES["cancelamentos"],
    }
    blocos = [
        bloco_indicadores(
            [
                ("Pedidos cancelados", r["quantidade"], "numero"),
                ("Valor cancelado", r["valor"], "moeda"),
                ("Taxa de cancelamento", r["taxa"], "percentual"),
                ("Pedidos de venda no período", r["pedidosNoPeriodo"], "numero"),
            ],
            f"Cancelamentos · {periodo.rotulo}",
        )
    ]
    if r["porMotivo"]:
        blocos.append(
            bloco_tabela(
                "Por motivo de origem",
                [("motivo", "Motivo", "texto"), ("quantidade", "Pedidos", "numero"), ("valor", "Valor", "moeda")],
                r["porMotivo"],
            )
        )
    if r["porCanal"]:
        blocos.append(
            bloco_tabela(
                "Por canal",
                [("canal", "Canal", "texto"), ("quantidade", "Pedidos", "numero"), ("valor", "Valor", "moeda")],
                r["porCanal"],
            )
        )
    blocos.append(
        bloco_fonte("consultar_cancelamentos", periodo.rotulo, filtros, DEFINICOES["cancelamentos"], _dados_ate(db, marca))
    )
    texto = f"{periodo.frase[:1].upper()}{periodo.frase[1:]}, {dados['cancelados']} pedidos de venda foram cancelados ({dados['valorCancelado']}), {dados['taxaDeCancelamento']} dos {dados['pedidosDeVendaNoPeriodo']} pedidos do período."
    if r["pedidosNoPeriodo"] == 0:
        texto = _sem_vendas(db, marca)
    return Resultado(dados=dados, blocos=blocos, texto=texto)


# ---------- Estoque ----------


class EstoqueBaixo(ComEscopo):
    categoria: str | None = Field(None, max_length=60)
    somente_com_demanda: bool = Field(True, description="true: só peças que venderam no local nos últimos 60 dias.")
    limite: int = Field(15, ge=1, le=30)


def _rotulo_status(status: str) -> str:
    return "Sem estoque" if status == "SEM_ESTOQUE" else "Estoque baixo"


def consultar_estoque_baixo(db: Session, ctx: Contexto, entrada: EstoqueBaixo) -> Resultado:
    marca, lojas, nome_loja = _escopo(db, ctx, entrada.marca, entrada.loja_id)
    r = analises.estoque_baixo(
        db,
        marca=marca,
        loja_id=lojas[0] if lojas else None,
        categoria=entrada.categoria,
        somente_com_demanda=entrada.somente_com_demanda,
        limite=entrada.limite,
    )
    extra = [f"Categoria: {entrada.categoria}"] if entrada.categoria else []
    extra.append(
        f"Só com venda nos últimos {r['janelaDias']} dias" if entrada.somente_com_demanda else "Inclui peças sem venda recente"
    )
    filtros = _filtros(marca, nome_loja, extra=extra)
    for item in r["itens"]:
        item["situacao"] = _rotulo_status(item["status"])
    dados = {
        "filtros": filtros,
        "itensNoMinimoOuZerados": numero(r["total"]),
        "zerados": numero(r["zerados"]),
        "mostrando": [
            {
                "produto": i["produto"],
                "sku": i["sku"],
                "cor": i["cor"],
                "tamanho": i["tamanho"],
                "loja": i["loja"],
                "saldo": i["quantidade"],
                "minimo": i["minimo"],
                "vendidasNaJanela": i["vendasJanela"],
            }
            for i in r["itens"]
        ],
        "definicao": DEFINICOES["estoque_baixo"],
    }
    colunas = [
        ("produto", "Produto", "texto"),
        ("sku", "SKU", "texto"),
        ("loja", "Loja", "texto"),
        ("quantidade", "Saldo", "numero"),
        ("minimo", "Mínimo", "numero"),
        ("vendasJanela", f"Vendas {r['janelaDias']} d", "numero"),
        ("situacao", "Situação", "texto"),
    ]
    blocos = [
        bloco_indicadores(
            [("Itens no mínimo ou zerados", r["total"], "numero"), ("Zerados", r["zerados"], "numero")], "Estoque baixo"
        ),
    ]
    if r["itens"]:
        blocos.append(
            bloco_tabela("Itens que pedem reposição", colunas, r["itens"], f"Mostrando {len(r['itens'])} de {r['total']}")
        )
    blocos.append(bloco_fonte("consultar_estoque_baixo", None, filtros, DEFINICOES["estoque_baixo"], None))
    if r["total"]:
        primeiro = r["itens"][0]
        texto = f"{dados['itensNoMinimoOuZerados']} itens estão no mínimo ou zerados ({dados['zerados']} zerados). O mais urgente: {primeiro['produto']} ({primeiro['sku']}) na {primeiro['loja']}, com {primeiro['quantidade']} peças e {primeiro['vendasJanela']} vendidas nos últimos {r['janelaDias']} dias."
    else:
        texto = "Nenhum item no mínimo ou zerado com esses filtros."
    return Resultado(dados=dados, blocos=blocos, texto=texto)


class EstoqueParado(ComEscopo):
    dias: int = Field(30, ge=7, le=365, description="Sem venda no local há pelo menos esses dias.")
    limite: int = Field(15, ge=1, le=30)


def consultar_estoque_parado(db: Session, ctx: Contexto, entrada: EstoqueParado) -> Resultado:
    marca, lojas, nome_loja = _escopo(db, ctx, entrada.marca, entrada.loja_id)
    r = analises.estoque_parado(db, marca=marca, loja_id=lojas[0] if lojas else None, dias=entrada.dias, limite=entrada.limite)
    filtros = _filtros(marca, nome_loja, [f"Sem venda há {entrada.dias} dias ou mais"])
    for item in r["itens"]:
        item["ultimaVendaTexto"] = data(item["ultimaVenda"]) if item["ultimaVenda"] else "sem venda no local"
    dados = {
        "filtros": filtros,
        "itensParados": numero(r["total"]),
        "pecasParadas": numero(r["pecas"]),
        "valorParado": brl(r["valor"]),
        "porLoja": [
            {
                "loja": linha["loja"],
                "itens": numero(linha["itens"]),
                "pecas": numero(linha["pecas"]),
                "valor": brl(linha["valor"]),
            }
            for linha in r["porLoja"]
        ],
        "maiores": [
            {
                "produto": i["produto"],
                "sku": i["sku"],
                "loja": i["loja"],
                "saldo": i["quantidade"],
                "ultimaVenda": i["ultimaVendaTexto"],
                "diasSemVenda": i["diasSemVenda"],
                "valor": brl(i["valor"]),
            }
            for i in r["itens"]
        ],
        "definicao": DEFINICOES["estoque_parado"],
    }
    blocos = [
        bloco_indicadores(
            [
                ("Itens parados", r["total"], "numero"),
                ("Peças paradas", r["pecas"], "numero"),
                ("Valor parado", r["valor"], "moeda"),
            ],
            f"Sem venda há {entrada.dias}+ dias",
        ),
    ]
    if r["porLoja"]:
        blocos.append(
            bloco_tabela(
                "Por loja",
                [
                    ("loja", "Loja", "texto"),
                    ("itens", "Itens", "numero"),
                    ("pecas", "Peças", "numero"),
                    ("valor", "Valor", "moeda"),
                ],
                r["porLoja"],
            )
        )
        blocos.append(
            bloco_grafico(
                "Valor parado por loja",
                "barras",
                "loja",
                [{"chave": "valor", "rotulo": "Valor parado"}],
                [{"x": linha["loja"], "valor": linha["valor"]} for linha in r["porLoja"]],
            )
        )
    if r["itens"]:
        colunas = [
            ("produto", "Produto", "texto"),
            ("sku", "SKU", "texto"),
            ("loja", "Loja", "texto"),
            ("quantidade", "Saldo", "numero"),
            ("ultimaVendaTexto", "Última venda", "texto"),
            ("diasSemVenda", "Dias sem venda", "numero"),
            ("valor", "Valor", "moeda"),
        ]
        blocos.append(
            bloco_tabela("Maiores valores parados", colunas, r["itens"], f"Mostrando {len(r['itens'])} de {r['total']}")
        )
    blocos.append(
        bloco_fonte(
            "consultar_estoque_parado", None, filtros, DEFINICOES["estoque_parado"], analise_repository.ultima_movimentacao_em(db)
        )
    )
    if r["total"]:
        loja = dados["porLoja"][0]
        texto = f"{dados['itensParados']} itens ({dados['pecasParadas']} peças, {dados['valorParado']}) estão sem venda há {entrada.dias} dias ou mais. A maior concentração está na {loja['loja']} ({loja['valor']})."
    else:
        texto = f"Nenhum item sem venda há {entrada.dias} dias ou mais com esses filtros."
    return Resultado(dados=dados, blocos=blocos, texto=texto)


class EstoquePorLoja(Entrada):
    marca: Marca | None = None


def consultar_estoque_por_loja(db: Session, ctx: Contexto, entrada: EstoquePorLoja) -> Resultado:
    marca, _, _ = _escopo(db, ctx, entrada.marca, None)
    linhas = analises.estoque_por_loja(db, marca=marca)
    filtros = _filtros(marca)
    dados = {
        "filtros": filtros,
        "lojas": [
            {
                "loja": linha["loja"],
                "tipo": linha["tipo"],
                "pecas": numero(linha["pecas"]),
                "valor": brl(linha["valor"]),
                "participacao": pct(linha["participacao"]),
            }
            for linha in linhas
        ],
        "definicao": DEFINICOES["valor_estoque"],
    }
    colunas = [
        ("loja", "Local", "texto"),
        ("pecas", "Peças", "numero"),
        ("skus", "SKUs com saldo", "numero"),
        ("valor", "Valor (preço de venda)", "moeda"),
        ("participacao", "% das peças", "percentual"),
    ]
    blocos = [
        bloco_tabela("Estoque por loja e CD", colunas, linhas),
        bloco_grafico(
            "Peças por local",
            "barras",
            "loja",
            [{"chave": "pecas", "rotulo": "Peças"}],
            [{"x": linha["loja"], "pecas": linha["pecas"]} for linha in linhas],
            "numero",
        ),
        bloco_fonte("consultar_estoque_por_loja", None, filtros, DEFINICOES["valor_estoque"], None),
    ]
    texto = (
        "Concentração de estoque: "
        + "; ".join(f"{linha['loja']} {linha['pecas']} peças ({linha['participacao']})" for linha in dados["lojas"][:4])
        + "."
        if linhas
        else "Nenhum estoque encontrado."
    )
    return Resultado(dados=dados, blocos=blocos, texto=texto)


class MaioresEstoques(ComEscopo):
    limite: int = Field(10, ge=1, le=20)


def consultar_maiores_estoques(db: Session, ctx: Contexto, entrada: MaioresEstoques) -> Resultado:
    marca, lojas, nome_loja = _escopo(db, ctx, entrada.marca, entrada.loja_id)
    linhas = analises.maiores_estoques(db, marca=marca, loja_id=lojas[0] if lojas else None, limite=entrada.limite)
    filtros = _filtros(marca, nome_loja)
    dados = {
        "filtros": filtros,
        "produtos": [
            {
                "produto": linha["produto"],
                "marca": NOME_MARCA[linha["marca"]],
                "pecas": numero(linha["pecas"]),
                "locais": linha["locais"],
                "valor": brl(linha["valor"]),
            }
            for linha in linhas
        ],
        "definicao": DEFINICOES["valor_estoque"],
    }
    colunas = [
        ("produto", "Produto", "texto"),
        ("categoria", "Categoria", "texto"),
        ("pecas", "Peças", "numero"),
        ("locais", "Locais", "numero"),
        ("valor", "Valor (preço de venda)", "moeda"),
    ]
    blocos = [
        bloco_tabela("Produtos com mais unidades em estoque", colunas, linhas),
        bloco_fonte("consultar_maiores_estoques", None, filtros, DEFINICOES["valor_estoque"], None),
    ]
    texto = (
        "Produtos com mais unidades: " + "; ".join(f"{p['produto']} ({p['pecas']} peças)" for p in dados["produtos"][:5]) + "."
        if linhas
        else "Nenhum produto com estoque nesse filtro."
    )
    return Resultado(dados=dados, blocos=blocos, texto=texto)


class Avarias(ComEscopo):
    periodo: NomePeriodo | None = Field(None, description="Vazio: todo o histórico. " + DESCRICAO_PERIODO)  # type: ignore[valid-type]
    de: str | None = None
    ate: str | None = None


def consultar_avarias(db: Session, ctx: Contexto, entrada: Avarias) -> Resultado:
    marca, lojas, nome_loja = _escopo(db, ctx, entrada.marca, entrada.loja_id)
    periodo = (
        resolver(entrada.periodo, hoje(), ler_data(entrada.de, "de"), ler_data(entrada.ate, "ate")) if entrada.periodo else None
    )
    r = analises.avarias(db, marca=marca, loja_id=lojas[0] if lojas else None, periodo=periodo)
    filtros = _filtros(marca, nome_loja)
    rotulo = periodo.rotulo if periodo else "todo o histórico"
    dados = {
        "periodo": rotulo,
        "filtros": filtros,
        "registros": numero(r["registros"]),
        "pecasAvariadas": numero(r["pecas"]),
        "dessasEstimadas": numero(r["estimadas"]),
        "porLoja": [
            {"loja": linha["loja"], "pecas": numero(linha["pecas"]), "estimadas": numero(linha["estimadas"])}
            for linha in r["porLoja"]
        ],
        "produtosComMaisAvarias": [
            {"produto": linha["produto"], "pecas": numero(linha["pecas"])} for linha in r["porProduto"][:10]
        ],
        "definicao": DEFINICOES["avarias"],
    }
    blocos = [
        bloco_indicadores(
            [
                ("Peças avariadas", r["pecas"], "numero"),
                ("Estimadas (não contadas)", r["estimadas"], "numero"),
                ("Registros", r["registros"], "numero"),
            ],
            f"Avarias · {rotulo}",
        )
    ]
    if r["porLoja"]:
        blocos.append(
            bloco_tabela(
                "Por loja",
                [("loja", "Loja", "texto"), ("pecas", "Peças", "numero"), ("estimadas", "Estimadas", "numero")],
                r["porLoja"],
            )
        )
    if r["porProduto"]:
        blocos.append(
            bloco_tabela(
                "Produtos com mais avarias",
                [("produto", "Produto", "texto"), ("pecas", "Peças", "numero"), ("estimadas", "Estimadas", "numero")],
                r["porProduto"][:10],
            )
        )
    blocos.append(bloco_fonte("consultar_avarias", rotulo, filtros, DEFINICOES["avarias"], None))
    if r["pecas"]:
        texto = f"{dados['pecasAvariadas']} peças avariadas em {rotulo} ({dados['dessasEstimadas']} estimadas, sem contagem). Produto com mais avarias: {r['porProduto'][0]['produto']} ({numero(r['porProduto'][0]['pecas'])} peças)."
    else:
        texto = f"Nenhuma avaria registrada em {rotulo} com esses filtros."
    return Resultado(dados=dados, blocos=blocos, texto=texto)


class Transferencias(Entrada):
    marca: Marca | None = None
    limite: int = Field(10, ge=1, le=20)


def sugerir_transferencias(db: Session, ctx: Contexto, entrada: Transferencias) -> Resultado:
    marca, _, _ = _escopo(db, ctx, entrada.marca, None)
    linhas = analises.sugestoes_transferencia(db, marca=marca, limite=entrada.limite)
    filtros = _filtros(marca)
    dados = {
        "filtros": filtros,
        "sugestoes": [
            {
                "sku": s["sku"],
                "produto": s["produto"],
                "de": s["origem"],
                "para": s["destino"],
                "quantidade": s["quantidade"],
                "vendasNoDestino60d": s["vendasDestino"],
                "livreNoDestino": s["livreDestino"],
            }
            for s in linhas
        ],
        "importante": "São sugestões para a equipe analisar. Nada é transferido automaticamente; a transferência é criada na tela de Transferências.",
        "definicao": DEFINICOES["transferencias"],
    }
    colunas = [
        ("produto", "Produto", "texto"),
        ("sku", "SKU", "texto"),
        ("origem", "De", "texto"),
        ("destino", "Para", "texto"),
        ("quantidade", "Qtd. sugerida", "numero"),
        ("livreDestino", "Livre no destino", "numero"),
        ("vendasDestino", "Vendas destino 60 d", "numero"),
    ]
    blocos = []
    if linhas:
        blocos.append(
            bloco_tabela("Sugestões de transferência (para análise)", colunas, linhas, "Nada é transferido automaticamente.")
        )
    blocos.append(bloco_fonte("sugerir_transferencias", None, filtros, DEFINICOES["transferencias"], None))
    if linhas:
        s = linhas[0]
        texto = f"Encontrei {len(linhas)} sugestões para análise. A primeira: levar {s['quantidade']} peças de {s['produto']} ({s['sku']}) da {s['origem']} para a {s['destino']}, que vendeu {s['vendasDestino']} nos últimos 60 dias. Nada é transferido automaticamente."
    else:
        texto = "Não encontrei peças em falta numa loja que sobrem em outro local da mesma marca."
    return Resultado(dados=dados, blocos=blocos, texto=texto)


# ---------- Lupe+ ----------


class Fidelidade(Entrada):
    dias_a_vencer: int = Field(30, ge=1, le=180)


ROTULO_CATEGORIA = {"BRONZE": "Bronze", "PRATA": "Prata", "OURO": "Ouro", "VIP": "Vip", "SEM_CATEGORIA": "Sem categoria"}


def consultar_fidelidade(db: Session, ctx: Contexto, entrada: Fidelidade) -> Resultado:
    r = analises.fidelidade(db, dias_a_vencer=entrada.dias_a_vencer)
    categorias = [
        {
            **linha,
            "nome": ROTULO_CATEGORIA[linha["categoria"]],
            "aVencer": r["clientesAVencerPorCategoria"].get(linha["categoria"], 0),
        }
        for linha in r["porCategoria"]
    ]
    dados = {
        "referencia": data(r["referencia"]),
        "clientesComSaldo": numero(r["clientesComSaldo"]),
        "pontosValidos": numero(r["pontosValidos"]),
        "valorEmReais": brl(r["valorValidos"]),
        "porCategoria": [
            {"categoria": c["nome"], "clientes": numero(c["clientes"]), "pontos": numero(c["pontos"])} for c in categorias
        ],
        f"pontosVencendoEm{entrada.dias_a_vencer}Dias": numero(r["pontosAVencer"]),
        "valorVencendo": brl(r["valorAVencer"]),
        "clientesComPontosVencendo": numero(r["clientesAVencer"]),
        "jaVencidosAindaNaoBaixados": numero(r["vencidosNaoBaixados"]),
        "definicao": DEFINICOES["pontos"],
        "dadosPessoais": "Só números agregados; a lista de clientes fica no atendimento.",
    }
    blocos = [
        bloco_indicadores(
            [
                ("Pontos válidos", r["pontosValidos"], "numero"),
                ("Valor em desconto", r["valorValidos"], "moeda"),
                ("Clientes com saldo", r["clientesComSaldo"], "numero"),
                (f"Vencendo em {entrada.dias_a_vencer} dias", r["pontosAVencer"], "numero"),
                ("Clientes com pontos vencendo", r["clientesAVencer"], "numero"),
            ],
            f"Lupe+ em {data(r['referencia'])}",
        ),
        bloco_tabela(
            "Clientes por categoria",
            [
                ("nome", "Categoria", "texto"),
                ("clientes", "Clientes", "numero"),
                ("pontos", "Pontos válidos", "numero"),
                ("aVencer", f"Com pontos vencendo ({entrada.dias_a_vencer} d)", "numero"),
            ],
            categorias,
        ),
        bloco_grafico(
            "Clientes por categoria",
            "barras",
            "nome",
            [{"chave": "clientes", "rotulo": "Clientes"}],
            [{"x": c["nome"], "clientes": c["clientes"]} for c in categorias],
            "numero",
        ),
        bloco_fonte(
            "consultar_fidelidade", data(r["referencia"]), ["Programa Lupe+ (as duas marcas)"], DEFINICOES["pontos"], None
        ),
    ]
    texto = f"O Lupe+ tem {dados['pontosValidos']} pontos válidos ({dados['valorEmReais']} em desconto) com {dados['clientesComSaldo']} clientes. Nos próximos {entrada.dias_a_vencer} dias vencem {numero(r['pontosAVencer'])} pontos ({dados['valorVencendo']}) de {dados['clientesComPontosVencendo']} clientes."
    return Resultado(dados=dados, blocos=blocos, texto=texto)


# ---------- Alertas ----------


class ConsultarAlertas(Entrada):
    tipo: Literal["ESTOQUE_BAIXO", "ESTOQUE_PARADO", "SUGESTAO_TRANSFERENCIA", "PONTOS_A_VENCER"] | None = None
    limite: int = Field(10, ge=1, le=30)


def consultar_alertas(db: Session, ctx: Contexto, entrada: ConsultarAlertas) -> Resultado:
    """Alertas abertos que este perfil pode ver (cada tipo pede o módulo do assunto)."""
    tipos = [t for t, modulo in MODULO_DO_ALERTA.items() if ctx.papel and pode_acessar(ctx.papel, modulo)]
    if entrada.tipo:
        if entrada.tipo not in tipos:
            raise FalhaFerramenta("SEM_PERMISSAO: o seu perfil não vê esse tipo de alerta.")
        tipos = [entrada.tipo]
    alertas = [
        a
        for a in alerta_repository.listar(db, tipos=tipos, status="ABERTO", limite=500)
        if na_marca(ctx.marca_escopo, a.marca) or a.marca is None
    ]
    contagem = {t: sum(1 for a in alertas if a.tipo == t) for t in tipos}
    mostrados = alertas[: entrada.limite]
    linhas = [
        {"tipo": a.tipo, "titulo": a.titulo, "severidade": a.severidade, "atualizado": data(a.atualizado_em)} for a in mostrados
    ]
    dados = {"abertosPorTipo": contagem, "alertas": linhas}
    blocos = (
        [
            bloco_tabela(
                "Alertas abertos",
                [("titulo", "Alerta", "texto"), ("severidade", "Severidade", "texto"), ("atualizado", "Visto em", "texto")],
                linhas,
            )
        ]
        if linhas
        else []
    )
    blocos.append({"tipo": "link", "rotulo": "Ver todos os alertas", "destino": "/inteligencia?aba=alertas"})
    texto = (
        f"Há {len(alertas)} alertas abertos."
        if alertas
        else "Não há alertas abertos para o seu perfil. As automações atualizam os alertas quando rodam."
    )
    return Resultado(dados=dados, blocos=blocos, texto=texto)


# ---------- Registro ----------

FERRAMENTAS = [
    Ferramenta(
        "consultar_faturamento",
        "Faturamento oficial (regra da diretoria), receita de vendas, devoluções, pedidos, ticket médio e cancelados de um "
        "período, com comparação opcional e quebra por marca, loja, canal, categoria ou tempo. Use para 'quanto faturamos', "
        "'qual marca vendeu mais', 'qual loja faturou mais'.",
        Faturamento,
        consultar_faturamento,
        modulo="financeiro",
    ),
    Ferramenta(
        "consultar_mais_vendidos",
        "Ranking dos produtos mais vendidos no período, por peças ou por valor, com filtros de marca, loja, canal e categoria.",
        MaisVendidos,
        consultar_mais_vendidos,
        modulo="financeiro",
    ),
    Ferramenta(
        "consultar_cancelamentos",
        "Pedidos de venda cancelados no período: quantidade, valor, taxa e motivo de origem (cancelada, estornada, chargeback...).",
        Cancelamentos,
        consultar_cancelamentos,
        modulo="financeiro",
    ),
    Ferramenta(
        "consultar_estoque_baixo",
        "Itens de estoque (loja + SKU) no mínimo ou zerados. Por padrão só os que venderam no local nos últimos 60 dias.",
        EstoqueBaixo,
        consultar_estoque_baixo,
        modulo="estoque",
    ),
    Ferramenta(
        "consultar_estoque_parado",
        "Itens com saldo e sem venda no local há N dias ou mais (padrão 30), com a última venda e o valor parado.",
        EstoqueParado,
        consultar_estoque_parado,
        modulo="estoque",
    ),
    Ferramenta(
        "consultar_estoque_por_loja",
        "Concentração do estoque: peças, SKUs e valor em cada loja e CD, com a participação de cada um.",
        EstoquePorLoja,
        consultar_estoque_por_loja,
        modulo="estoque",
    ),
    Ferramenta(
        "consultar_maiores_estoques",
        "Produtos com mais unidades em estoque (somadas nos locais), com o valor a preço de venda.",
        MaioresEstoques,
        consultar_maiores_estoques,
        modulo="estoque",
    ),
    Ferramenta(
        "consultar_avarias",
        "Peças avariadas (movimentações de AVARIA) por loja e por produto, no período ou em todo o histórico.",
        Avarias,
        consultar_avarias,
        modulo="estoque",
    ),
    Ferramenta(
        "sugerir_transferencias",
        "Sugestões de transferência entre locais da mesma marca (sobra em um, falta com demanda em outro), só para análise humana.",
        Transferencias,
        sugerir_transferencias,
        modulo="transferencias",
    ),
    Ferramenta(
        "consultar_fidelidade",
        "Números do Lupe+ sem dado pessoal: pontos válidos e valor, clientes por categoria e pontos que vencem nos próximos dias.",
        Fidelidade,
        consultar_fidelidade,
        modulo="financeiro",
    ),
    Ferramenta(
        "consultar_alertas",
        "Alertas operacionais abertos (estoque baixo, estoque parado, sugestões de transferência, pontos a vencer) que o perfil pode ver.",
        ConsultarAlertas,
        consultar_alertas,
        modulo="dashboard",
    ),
]


def lojas_do_contexto(db: Session, marca: str | None) -> list[dict]:
    """Lojas e CD que a pessoa vê, para o modelo saber os ids (vão no contexto, não numa ferramenta)."""
    return [
        {"id": loja.id, "nome": loja.nome, "marca": loja.marca, "tipo": loja.tipo}
        for loja in cadastro_repository.lojas(db, somente_ativas=True)
        if na_marca(marca, loja.marca)
    ]
