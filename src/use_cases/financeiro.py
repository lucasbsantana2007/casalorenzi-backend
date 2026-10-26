"""Visão financeira: receita, pedidos, ticket médio, estoque valorizado, pós-venda e devoluções.

Receita = o total dos pedidos de venda não cancelados (itens − desconto + frete), a mesma regra do
faturamento da diretoria. Troca não é receita. Com filtro de categoria ou gênero, só os itens que batem
entram (desconto e frete não se dividem por item).
devolucoesValor soma o valor reembolsado no período; receitaLiquida = receita − devoluções. Devolução sem
pedido de origem (Vulto) entra pela loja em que foi registrada: loja física → Loja física, CD → E-commerce.
porLoja e porCanal trazem também as devoluções e a receitaLiquida de cada um, com a mesma atribuição (a soma
das lojas, e a dos canais, fecha com o total)."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src import models as m
from src.entities.pedido import CANAIS, TIPOS_SEM_RECEITA
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
    marca: str | None = None,
) -> dict:
    """Filtros em listas separadas por vírgula (ex.: lojas=1,3&canais=E-commerce). marca: só as lojas
    dessa marca (escopo do funcionário; None = as duas)."""
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
    if marca:
        da_marca = [loja.id for loja in cadastro_repository.lojas(db, marca=marca)]
        filtro_lojas = [x for x in filtro_lojas if x in da_marca] if filtro_lojas else da_marca
        filtro_lojas = filtro_lojas or [0]  # nenhuma loja da marca no filtro: nada entra
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
        if pedido.tipo in TIPOS_SEM_RECEITA:  # troca lançada como pedido não é venda (decisão 16 da Vulto)
            return None
        if filtro_lojas and pedido.loja_id not in filtro_lojas:
            return None
        if filtro_canais and pedido.canal not in filtro_canais:
            return None
        itens = [i for i in pedido.itens if not filtra_produto or produto_valido(i.variacao.produto)]
        if not itens:
            return None
        valor = sum(float(i.preco_unitario) * i.quantidade for i in itens) if filtra_produto else float(pedido.total)
        return {
            "loja_id": pedido.loja_id,
            "canal": pedido.canal,
            "status": pedido.status,
            "criado_em": pedido.criado_em,
            "itens": itens,
            "total": valor,
        }

    # Só a janela do período e da comparação (a base da Vulto tem dezenas de milhares de pedidos)
    comp = None if comparar == "nenhum" else intervalo_comparacao(inicio, fim, comparar)
    janela = (min(inicio, comp[0]) if comp else inicio, max(fim, comp[1]) if comp else fim)
    pedidos = pedido_repository.no_periodo(db, *janela, lojas=filtro_lojas or None)
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
    atendimentos = atendimento_repository.no_periodo(db, *janela)
    # Atendimento sobre um pedido anterior à janela: o pedido vem à parte (só com filtro de canal ou produto)
    if filtro_canais or filtra_produto:
        faltando = {a.pedido_id for a in atendimentos if a.pedido_id and a.pedido_id not in por_id}
        por_id.update({p.id: p for p in pedido_repository.por_ids(db, faltando)})
    for a in atendimentos:
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

    def origem_devolucao(d: m.Devolucao) -> tuple[int, str]:
        """Loja e canal a que a devolução pertence: os do pedido de origem (que pode ser de outra loja ou de
        antes do período carregado); sem pedido, a loja em que foi registrada."""
        pedido = d.pedido
        loja_id = pedido.loja_id if pedido else d.loja_id
        canal = pedido.canal if pedido else ("Loja física" if d.loja.tipo == "LOJA" else "E-commerce")
        return loja_id, canal

    def devolucao_conta(d: m.Devolucao) -> bool:
        if d.pedido is not None and d.pedido.tipo in TIPOS_SEM_RECEITA:
            return False
        loja_id, canal = origem_devolucao(d)
        if filtro_lojas and loja_id not in filtro_lojas:
            return False
        if filtro_canais and canal not in filtro_canais:
            return False
        return not filtra_produto or produto_valido(d.variacao.produto)

    devolvido = [
        (d.criada_em, float(d.valor_devolvido), *origem_devolucao(d))
        for d in devolucao_repository.listar(db, desde=min(inicio, comp[0]) if comp else inicio, ate=fim)
        if devolucao_conta(d)
    ]

    def valor_devolvido(a: datetime, b: datetime, loja_id: int | None = None, canal: str | None = None) -> float:
        return sum(
            valor
            for quando, valor, loja, canal_dev in devolvido
            if a <= quando < b and (loja_id is None or loja == loja_id) and (canal is None or canal_dev == canal)
        )

    devolvido_atual = valor_devolvido(inicio, fim)
    devolvido_anterior = valor_devolvido(*comp) if comp else None

    # Faturamento líquido de cada loja e de cada canal, com a mesma atribuição das devoluções
    for linha in por_loja:
        linha["devolucoes"] = valor_devolvido(inicio, fim, loja_id=linha["loja"]["id"])
        linha["receitaLiquida"] = linha["receita"] - linha["devolucoes"]
    por_canal = []
    for canal in CANAIS:
        if filtro_canais and canal not in filtro_canais:
            continue
        do_canal = [p for p in atual if p["canal"] == canal]
        devolvido_canal = valor_devolvido(inicio, fim, canal=canal)
        por_canal.append(
            {
                "canal": canal,
                "receita": soma(do_canal),
                "pedidos": len(do_canal),
                "devolucoes": devolvido_canal,
                "receitaLiquida": soma(do_canal) - devolvido_canal,
            }
        )
    return {
        "receita": soma(atual),
        "receitaAnterior": soma(anterior) if comp else None,
        # Receita menos devoluções: o faturamento da diretoria
        "receitaLiquida": soma(atual) - devolvido_atual,
        "receitaLiquidaAnterior": soma(anterior) - devolvido_anterior if comp else None,
        "pedidos": len(atual),
        "pedidosAnterior": len(anterior) if comp else None,
        "pecas": pecas(atual),
        "pecasAnterior": pecas(anterior) if comp else None,
        "cancelados": sum(1 for p in entre(recortados, inicio, fim) if p["status"] == "CANCELADO"),
        "valorEstoque": valor_estoque(estoques),
        "taxaPosVenda": total_pos_venda / pedidos_no_periodo if pedidos_no_periodo else 0,
        "devolucoesValor": devolvido_atual,
        "devolucoesValorAnterior": devolvido_anterior,
        "porLoja": por_loja,
        "porCanal": por_canal,
        "porCategoria": por_categoria,
        "serie": serie,
        "posVenda": pos_venda_serie,
    }
