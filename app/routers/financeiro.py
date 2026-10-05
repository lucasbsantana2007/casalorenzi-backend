"""Visão financeira: receita, pedidos, ticket médio, estoque valorizado e pós-venda."""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import FUSO
from app.database import get_db
from app.models import Atendimento, Categoria, Estoque, Loja, Pedido, Usuario
from app.security import exigir_modulo
from app.utils import agora, inicio_do_dia, ler_data, lista_csv, ms
from app.views import loja_view

router = APIRouter(prefix="/financeiro", tags=["Financeiro"])


def _intervalo_comparacao(inicio: datetime, fim: datetime, comparar: str) -> tuple[datetime, datetime]:
    if comparar == "ano":
        def menos_um_ano(d: datetime) -> datetime:
            try:
                return d.replace(year=d.year - 1)
            except ValueError:  # 29/02
                return d.replace(year=d.year - 1, day=28)

        return menos_um_ano(inicio), menos_um_ano(fim)
    return inicio - (fim - inicio), inicio


def _baldes(inicio: datetime, fim: datetime, agrupar: str) -> list[tuple[datetime, datetime]]:
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


@router.get("/resumo")
def obter_resumo(
    de: str | None = None,
    ate: str | None = None,
    comparar: Literal["anterior", "ano", "nenhum"] = "anterior",
    agrupar: Literal["dia", "semana", "mes"] = "dia",
    lojas: str | None = None,
    canais: str | None = None,
    categorias: str | None = None,
    generos: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_modulo("financeiro")),
):
    """Filtros em listas separadas por vírgula (ex.: lojas=1,3&canais=E-commerce)."""
    hoje = agora().astimezone(FUSO).date()
    dia_inicial = ler_data(de, "de") or hoje - timedelta(days=29)
    dia_final = ler_data(ate, "ate") or hoje
    if dia_final < dia_inicial:
        raise HTTPException(422, "A data final deve ser igual ou posterior à inicial.")
    inicio = inicio_do_dia(dia_inicial)
    fim = inicio_do_dia(dia_final + timedelta(days=1))

    try:
        filtro_lojas = [int(x) for x in lista_csv(lojas)]
    except ValueError:
        raise HTTPException(422, "Lista de lojas inválida.") from None
    filtro_canais = lista_csv(canais)
    filtro_categorias = lista_csv(categorias)
    filtro_generos = lista_csv(generos)
    filtra_produto = bool(filtro_categorias or filtro_generos)

    def produto_valido(produto) -> bool:
        return (not filtro_categorias or produto.categoria.nome in filtro_categorias) and (
            not filtro_generos or produto.genero in filtro_generos
        )

    # Pedido recortado pelos filtros: com filtro de produto, só os itens que batem entram na receita
    def recortar(pedido: Pedido) -> dict | None:
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

    pedidos = db.scalars(select(Pedido).options(selectinload(Pedido.itens))).all()
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
    comp = None if comparar == "nenhum" else _intervalo_comparacao(inicio, fim, comparar)
    anterior = entre(validos, *comp) if comp else []

    # Estoque é uma foto do momento: respeita loja, categoria e gênero, mas não o período
    estoques = [
        e
        for e in db.scalars(select(Estoque))
        if (not filtro_lojas or e.loja_id in filtro_lojas) and produto_valido(e.variacao.produto)
    ]

    def valor_estoque(lista) -> float:
        return sum(e.quantidade * float(e.variacao.produto.preco_base) for e in lista)

    por_loja = []
    for loja in db.scalars(select(Loja).order_by(Loja.id)):
        if filtro_lojas and loja.id not in filtro_lojas:
            continue
        da_loja = [p for p in atual if p["loja_id"] == loja.id]
        por_loja.append(
            {
                "loja": loja_view(loja),
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
        for categoria in db.scalars(select(Categoria.nome).order_by(Categoria.id))
        if not filtro_categorias or categoria in filtro_categorias
    ]
    por_categoria.sort(key=lambda c: (-c["receita"], -c["valorEstoque"]))

    periodos = _baldes(inicio, fim, agrupar)
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
    for a in db.scalars(select(Atendimento)):
        tipo = a.tipo_solicitacao.conta_pos_venda
        if tipo not in ("TROCA", "DEVOLUCAO"):
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
        "porLoja": por_loja,
        "porCategoria": por_categoria,
        "serie": serie,
        "posVenda": pos_venda_serie,
    }
