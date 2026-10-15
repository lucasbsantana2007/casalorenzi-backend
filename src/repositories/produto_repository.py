from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src import models as m
from src.entities.transferencia import PENDENTES


def obter(db: Session, produto_id: int) -> m.Produto | None:
    return db.scalar(select(m.Produto).options(selectinload(m.Produto.variacoes)).where(m.Produto.id == produto_id))


def listar(db: Session, categoria: str | None = None, ativo: bool | None = None, marca: str | None = None) -> list[m.Produto]:
    consulta = (
        select(m.Produto)
        .join(m.Produto.categoria)
        .options(selectinload(m.Produto.variacoes))
        .where(m.Produto.removido_em.is_(None))
        .order_by(m.Produto.id)
    )
    if categoria:
        consulta = consulta.where(m.Categoria.nome == categoria)
    if ativo is not None:
        consulta = consulta.where(m.Produto.ativo.is_(ativo))
    if marca:
        consulta = consulta.where(m.Produto.marca == marca)
    return list(db.scalars(consulta))


def variacao_por_grafia(db: Session, normalizada: str, quando: date | None = None) -> tuple[m.Variacao, m.SkuAlias | None] | None:
    """Variação de uma grafia de SKU (já normalizada) numa data. A busca é pelos aliases, que têm a
    vigência dos códigos reaproveitados; sem data, vale o alias sem fim de vigência (a peça atual).
    Sem alias, o próprio SKU (os da Casa Lorenzi não têm aliases)."""
    aliases = list(db.scalars(select(m.SkuAlias).where(m.SkuAlias.alias_normalizado == normalizada)))
    if quando is not None:
        aliases = [a for a in aliases if (a.valido_de or quando) <= quando <= (a.valido_ate or quando)]
    if aliases:
        alias = min(aliases, key=lambda a: (a.valido_ate is not None, a.id))
        return alias.variacao, alias
    variacao = db.scalar(select(m.Variacao).where(func.upper(m.Variacao.sku) == normalizada))
    return (variacao, None) if variacao else None


def variacao(db: Session, variacao_id: int) -> m.Variacao | None:
    return db.get(m.Variacao, variacao_id)


def em_andamento(db: Session, produto_id: int) -> tuple[int, int]:
    """(pedidos em processamento, transferências pendentes) com peças do produto."""
    pedidos = db.scalar(
        select(func.count(func.distinct(m.Pedido.id)))
        .join(m.Pedido.itens)
        .join(m.ItemPedido.variacao)
        .where(m.Variacao.produto_id == produto_id, m.Pedido.status == "PROCESSANDO")
    )
    transferencias = db.scalar(
        select(func.count(m.Transferencia.id))
        .join(m.Transferencia.variacao)
        .where(m.Variacao.produto_id == produto_id, m.Transferencia.status.in_(PENDENTES))
    )
    return pedidos or 0, transferencias or 0


def sku_em_uso(db: Session, skus: list[str], exceto_produto_id: int | None = None) -> m.Variacao | None:
    consulta = select(m.Variacao).where(m.Variacao.sku.in_(skus))
    if exceto_produto_id is not None:
        consulta = consulta.where(m.Variacao.produto_id != exceto_produto_id)
    return db.scalar(consulta)


def todas_variacoes(db: Session, marca: str | None = None) -> list[m.Variacao]:
    consulta = select(m.Variacao).order_by(m.Variacao.id)
    if marca:
        consulta = consulta.join(m.Variacao.produto).where(m.Produto.marca == marca)
    return list(db.scalars(consulta))
