"""Consultas agregadas para o copiloto gerencial e as automações (src/use_cases/analises.py).

Só SELECT, sempre com parâmetros (nada de texto do usuário ou do modelo montando SQL). As regras de
negócio (o que é venda, o que é cancelado) vêm de src/entities, as mesmas do financeiro.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src import models as m
from src.entities.pedido import TIPOS_SEM_RECEITA


def _no_escopo(consulta, *, marca: str | None, lojas: list[int] | None):
    if marca:
        consulta = consulta.where(m.Loja.marca == marca)
    if lojas:
        consulta = consulta.where(m.Loja.id.in_(lojas))
    return consulta


def vendas_por_estoque_desde(db: Session, desde: datetime) -> dict[int, int]:
    """Peças que saíram por venda de cada item de estoque (loja + SKU) desde o instante."""
    linhas = db.execute(
        select(m.Movimentacao.estoque_id, func.sum(-m.Movimentacao.quantidade))
        .where(m.Movimentacao.tipo == "VENDA", m.Movimentacao.criado_em >= desde)
        .group_by(m.Movimentacao.estoque_id)
    )
    return {estoque_id: int(total or 0) for estoque_id, total in linhas}


def ultima_venda_por_estoque(db: Session) -> dict[int, datetime]:
    linhas = db.execute(
        select(m.Movimentacao.estoque_id, func.max(m.Movimentacao.criado_em))
        .where(m.Movimentacao.tipo == "VENDA")
        .group_by(m.Movimentacao.estoque_id)
    )
    return dict(linhas.all())


def primeira_movimentacao_por_estoque(db: Session) -> dict[int, datetime]:
    linhas = db.execute(select(m.Movimentacao.estoque_id, func.min(m.Movimentacao.criado_em)).group_by(m.Movimentacao.estoque_id))
    return dict(linhas.all())


def mais_vendidos(
    db: Session,
    inicio: datetime,
    fim: datetime,
    *,
    marca: str | None,
    lojas: list[int] | None,
    canal: str | None,
    categoria: str | None,
    ordenar_por: str,
    limite: int,
) -> list:
    """Peças e valor (preço × quantidade dos itens) por produto, de pedidos de venda não cancelados criados
    em [inicio, fim). A peça não identificada no caixa (SO_HISTORICO) fica fora do ranking."""
    pecas = func.sum(m.ItemPedido.quantidade).label("pecas")
    valor = func.sum(m.ItemPedido.quantidade * m.ItemPedido.preco_unitario).label("valor")
    consulta = (
        select(
            m.Produto.id,
            m.Produto.nome,
            m.Produto.marca,
            m.Categoria.nome.label("categoria"),
            pecas,
            valor,
            func.count(func.distinct(m.Pedido.id)).label("pedidos"),
        )
        .select_from(m.ItemPedido)
        .join(m.Pedido, m.Pedido.id == m.ItemPedido.pedido_id)
        .join(m.Loja, m.Loja.id == m.Pedido.loja_id)
        .join(m.Variacao, m.Variacao.id == m.ItemPedido.variacao_id)
        .join(m.Produto, m.Produto.id == m.Variacao.produto_id)
        .join(m.Categoria, m.Categoria.id == m.Produto.categoria_id)
        .where(
            m.Pedido.criado_em >= inicio,
            m.Pedido.criado_em < fim,
            m.Pedido.tipo.not_in(TIPOS_SEM_RECEITA),
            m.Pedido.status != "CANCELADO",
            m.Variacao.status != "SO_HISTORICO",
        )
        .group_by(m.Produto.id, m.Produto.nome, m.Produto.marca, m.Categoria.nome)
    )
    consulta = _no_escopo(consulta, marca=marca, lojas=lojas)
    if canal:
        consulta = consulta.where(m.Pedido.canal == canal)
    if categoria:
        consulta = consulta.where(m.Categoria.nome == categoria)
    ordem = (valor.desc(), pecas.desc()) if ordenar_por == "valor" else (pecas.desc(), valor.desc())
    return list(db.execute(consulta.order_by(*ordem, m.Produto.nome).limit(limite)))


def pedidos_de_venda(db: Session, inicio: datetime, fim: datetime, *, marca: str | None, lojas: list[int] | None) -> list:
    """(status, status_origem, canal, quantidade, valor) dos pedidos de venda (trocas fora) criados no período."""
    consulta = (
        select(
            m.Pedido.status,
            m.Pedido.status_origem,
            m.Pedido.canal,
            func.count(m.Pedido.id).label("quantidade"),
            func.coalesce(func.sum(m.Pedido.total), 0).label("valor"),
        )
        .join(m.Loja, m.Loja.id == m.Pedido.loja_id)
        .where(m.Pedido.criado_em >= inicio, m.Pedido.criado_em < fim, m.Pedido.tipo.not_in(TIPOS_SEM_RECEITA))
        .group_by(m.Pedido.status, m.Pedido.status_origem, m.Pedido.canal)
    )
    return list(db.execute(_no_escopo(consulta, marca=marca, lojas=lojas)))


def avarias(db: Session, inicio: datetime | None, fim: datetime | None, *, marca: str | None, loja_id: int | None) -> list:
    """Movimentações de AVARIA com a peça e o local."""
    consulta = (
        select(
            m.Movimentacao.criado_em,
            m.Movimentacao.quantidade,
            m.Movimentacao.estimado,
            m.Loja.id.label("loja_id"),
            m.Loja.nome.label("loja"),
            m.Variacao.sku,
            m.Variacao.cor,
            m.Variacao.tamanho,
            m.Produto.id.label("produto_id"),
            m.Produto.nome.label("produto"),
        )
        .join(m.Estoque, m.Estoque.id == m.Movimentacao.estoque_id)
        .join(m.Loja, m.Loja.id == m.Estoque.loja_id)
        .join(m.Variacao, m.Variacao.id == m.Estoque.variacao_id)
        .join(m.Produto, m.Produto.id == m.Variacao.produto_id)
        .where(m.Movimentacao.tipo == "AVARIA")
        .order_by(m.Movimentacao.criado_em.desc())
    )
    if inicio:
        consulta = consulta.where(m.Movimentacao.criado_em >= inicio)
    if fim:
        consulta = consulta.where(m.Movimentacao.criado_em < fim)
    if marca:
        consulta = consulta.where(m.Loja.marca == marca)
    if loja_id:
        consulta = consulta.where(m.Loja.id == loja_id)
    return list(db.execute(consulta))


def ultimo_pedido_em(db: Session, marca: str | None = None) -> datetime | None:
    """Quando foi criado o pedido mais recente (até onde os dados de vendas vão)."""
    consulta = select(func.max(m.Pedido.criado_em)).join(m.Loja, m.Loja.id == m.Pedido.loja_id)
    if marca:
        consulta = consulta.where(m.Loja.marca == marca)
    return db.scalar(consulta)


def ultima_movimentacao_em(db: Session) -> datetime | None:
    return db.scalar(select(func.max(m.Movimentacao.criado_em)))
