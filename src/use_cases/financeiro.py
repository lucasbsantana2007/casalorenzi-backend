"""Visão financeira: receita, pedidos, ticket médio, estoque valorizado, pós-venda e devoluções.

devolucoesValor/devolucoesValorAnterior somam o valor reembolsado (valor_devolvido) no período e
no período de comparação. A receita continua bruta: quem quiser a líquida subtrai as devoluções."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.repositories import (
    atendimento_repository,
    cadastro_repository,
    devolucao_repository,
    estoque_repository,
    pedido_repository,
)
from src.schemas.comum import loja_saida
from src.utils.datas import hoje, inicio_do_dia, ler_data, ms
from src.utils.erros import DadosInvalidos
from src.utils.texto import lista_csv

TIPOS_POS_VENDA = ("TROCA", "DEVOLUCAO")


def intervalo_comparacao(inicio: datetime, fim: datetime, comparar: str) -> tuple[datetime, datetime]:
    """'ano': mesmo período do ano anterior; 'anterior': o período imediatamente antes."""
    if comparar == "ano":

        def menos_um_ano(d: datetime) -> datetime:
            try:
                return d.replace(year=d.year - 1)
            except ValueError:  # 29/02
                return d.replace(year=d.year - 1, day=28)

        return menos_um_ano(inicio), menos_um_ano(fim)
    return inicio - (fim - inicio), inicio


def baldes(inicio: datetime, fim: datetime, agrupar: str) -> list[tuple[datetime, datetime]]:
    """Divide [inicio, fim) em dias, semanas (a partir do início) ou meses de calendário."""
    resultado = []
    atual = inicio
    while atual < fim:
        if agrupar == "mes":
            proximo = (atual.replace(day=1) + timedelta(days=32)).replace(day=1)
        else:
            proximo = atual + timedelta(days=7 if agrupar == "semana" else 1)
        resultado.append((atual, min(proximo, fim)))
        atual = proximo
    return resultado


def resumo(
    db: Session,
    *,
    de: str | None,
    ate: str | None,
    comparar: str,
    agrupar: str,
    lojas: str | None,
    canais: str | None,
    categorias: str | None,
    generos: str | None,
) -> dict:
    """Filtros em listas separadas por vírgula (ex.: lojas=1,3&canais=E-commerce)."""
    dia_inicial = ler_data(de, "de") or hoje() - timedelta(days=29)
    dia_final = ler_data(ate, "ate") or hoje()
    if dia_final < dia_inicial:
        raise DadosInvalidos("A data final deve ser igual ou posterior à inicial.")
    inicio = inicio_do_dia(dia_inicial)
    fim = inicio_do_dia(dia_final + timedelta(days=1))

    try:
        filtro_lojas = [int(x) for x in lista_csv(lojas)]
    except ValueError:
        raise DadosInvalidos("Lista de lojas inválida.") from None
    filtro_canais = lista_csv(canais)
    filtro_categorias = lista_csv(categorias)
    filtro_generos = lista_csv(generos)
    filtra_produto = bool(filtro_categorias or filtro_generos)

    def produto_valido(produto: m.Produto) -> bool:
        return (not filtro_categorias or produto.categoria.nome in filtro_categorias) and (
            not filtro_generos or produto.genero in filtro_generos
        )

    # Pedido recortado pelos filtros: com filtro de produto, só os itens que batem entram na receita
    def recortar(pedido: m.Pedido) -> dict | None:
        if filtro_lojas and pedido.loja_id not in filtro_lojas:
            return None
        if filtro_canais and pedido.canal not in filtro_canais:
            return None
        itens = [i for i in pedido.itens if not filtra_produto or produto_valido(i.variacao.produto)]
        if not itens:
            return None
        return {
            "loja_id": pedido.loja_id,
            "status": pedido.status,
            "criado_em": pedido.criado_em,
            "itens": itens,
            "total": sum(float(i.preco_unitario) * i.quantidade for i in itens),
        }

    pedidos = pedido_repository.todos(db)
    por_id = {p.id: p for p in pedidos}
    recortados = [r for r in map(recortar, pedidos) if r]
    validos = [p for p in recortados if p["status"] != "CANCELADO"]

    def entre(colecao, a, b):
        return [p for p in colecao if a <= p["criado_em"] < b]

    def soma(lista):
        return sum(p["total"] for p in lista)

    def pecas(lista):
        return sum(i.quantidade for p in lista for i in p["itens"])

    atual = entre(validos, inicio, fim)
    comp = None if comparar == "nenhum" else intervalo_comparacao(inicio, fim, comparar)
    anterior = entre(validos, *comp) if comp else []

    # Estoque é uma foto do momento: respeita loja, categoria e gênero, mas não o período
    estoques = [
        e
        for e in estoque_repository.listar(db)
        if (not filtro_lojas or e.loja_id in filtro_lojas) and produto_valido(e.variacao.produto)
    ]

    def valor_estoque(lista) -> float:
        return sum(e.quantidade * float(e.variacao.produto.preco_base) for e in lista)

    por_loja = []
    for loja in cadastro_repository.lojas(db):
        if filtro_lojas and loja.id not in filtro_lojas:
            continue
        da_loja = [p for p in atual if p["loja_id"] == loja.id]
        por_loja.append(
            {
                "loja": loja_saida(loja),
                "receita": soma(da_loja),
                "receitaAnterior": soma([p for p in anterior if p["loja_id"] == loja.id]) if comp else None,
                "pedidos": len(da_loja),
                "ticketMedio": soma(da_loja) / len(da_loja) if da_loja else 0,
                "valorEstoque": valor_estoque([e for e in estoques if e.loja_id == loja.id]),
            }
        )

    def receita_categoria(lista, categoria: str) -> float:
        return sum(
            float(i.preco_unitario) * i.quantidade
            for p in lista
            for i in p["itens"]
            if i.variacao.produto.categoria.nome == categoria
        )

    por_categoria = [
        {
            "categoria": categoria,
            "receita": receita_categoria(atual, categoria),
            "receitaAnterior": receita_categoria(anterior, categoria) if comp else None,
            "valorEstoque": valor_estoque([e for e in estoques if e.variacao.produto.categoria.nome == categoria]),
        }
        for categoria in cadastro_repository.nomes_categorias(db)
        if not filtro_categorias or categoria in filtro_categorias
    ]
    por_categoria.sort(key=lambda c: (-c["receita"], -c["valorEstoque"]))

    periodos = baldes(inicio, fim, agrupar)
    deslocamento = (comp[0] - inicio) if comp else timedelta(0)
    serie = [
        {
            "data": ms(a),
            "receita": soma(entre(validos, a, b)),
            "receitaAnterior": soma(entre(validos, a + deslocamento, b + deslocamento)) if comp else None,
        }
        for a, b in periodos
    ]

    # Pós-venda: trocas e devoluções; com filtro de canal/produto, só as ligadas a um pedido que bate
    pos_venda = []
    for a in atendimento_repository.todos(db):
        tipo = a.tipo_solicitacao.conta_pos_venda
        if tipo not in TIPOS_POS_VENDA:
            continue
        if filtro_lojas and a.loja_id not in filtro_lojas:
            continue
        if filtro_canais or filtra_produto:
            pedido = por_id.get(a.pedido_id) if a.pedido_id else None
            if not (pedido and recortar(pedido)):
                continue
        pos_venda.append((tipo, a.criado_em))

    pos_venda_serie = []
    for a, b in periodos:
        n_pedidos = len(entre(recortados, a, b))
        trocas = sum(1 for tipo, quando in pos_venda if tipo == "TROCA" and a <= quando < b)
        devolucoes = sum(1 for tipo, quando in pos_venda if tipo == "DEVOLUCAO" and a <= quando < b)
        pos_venda_serie.append(
            {
                "data": ms(a),
                "pedidos": n_pedidos,
                "trocas": trocas,
                "devolucoes": devolucoes,
                "taxa": (trocas + devolucoes) / n_pedidos if n_pedidos else 0,
            }
        )
    pedidos_no_periodo = len(entre(recortados, inicio, fim))
    total_pos_venda = sum(s["trocas"] + s["devolucoes"] for s in pos_venda_serie)

    # Valor reembolsado em devoluções (tabela devolucoes). Respeita os mesmos filtros da receita:
    # loja e canal do pedido de origem (não a loja que recebeu a peça) e categoria/gênero do produto.
    itens_por_id = {i.id: i for p in pedidos for i in p.itens}

    def devolucao_conta(d: m.Devolucao) -> bool:
        pedido = por_id.get(d.pedido_id)
        if pedido is None:
            return False
        if filtro_lojas and pedido.loja_id not in filtro_lojas:
            return False
        if filtro_canais and pedido.canal not in filtro_canais:
            return False
        item = itens_por_id.get(d.item_pedido_id)
        return not filtra_produto or (item is not None and produto_valido(item.variacao.produto))

    devolvido = [
        (d.criada_em, float(d.valor_devolvido))
        for d in devolucao_repository.listar(db, desde=min(inicio, comp[0]) if comp else inicio, ate=fim)
        if devolucao_conta(d)
    ]

    def valor_devolvido(a: datetime, b: datetime) -> float:
        return sum(valor for quando, valor in devolvido if a <= quando < b)

    return {
        "receita": soma(atual),
        "receitaAnterior": soma(anterior) if comp else None,
        "pedidos": len(atual),
        "pedidosAnterior": len(anterior) if comp else None,
        "pecas": pecas(atual),
        "pecasAnterior": pecas(anterior) if comp else None,
        "cancelados": sum(1 for p in entre(recortados, inicio, fim) if p["status"] == "CANCELADO"),
        "valorEstoque": valor_estoque(estoques),
        "taxaPosVenda": total_pos_venda / pedidos_no_periodo if pedidos_no_periodo else 0,
        "devolucoesValor": valor_devolvido(inicio, fim),
        "devolucoesValorAnterior": valor_devolvido(*comp) if comp else None,
        "porLoja": por_loja,
        "porCategoria": por_categoria,
        "serie": serie,
        "posVenda": pos_venda_serie,
    }
