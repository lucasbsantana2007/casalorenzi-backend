from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src import models as m


def obter(db: Session, produto_id: int) -> m.Produto | None:
    return db.scalar(select(m.Produto).options(selectinload(m.Produto.variacoes)).where(m.Produto.id == produto_id))


def listar(db: Session, categoria: str | None = None, ativo: bool | None = None) -> list[m.Produto]:
    consulta = select(m.Produto).join(m.Produto.categoria).options(selectinload(m.Produto.variacoes)).order_by(m.Produto.id)
    if categoria:
        consulta = consulta.where(m.Categoria.nome == categoria)
    if ativo is not None:
        consulta = consulta.where(m.Produto.ativo.is_(ativo))
    return list(db.scalars(consulta))


def variacao(db: Session, variacao_id: int) -> m.Variacao | None:
    return db.get(m.Variacao, variacao_id)


def sku_em_uso(db: Session, skus: list[str], exceto_produto_id: int | None = None) -> m.Variacao | None:
    consulta = select(m.Variacao).where(m.Variacao.sku.in_(skus))
    if exceto_produto_id is not None:
        consulta = consulta.where(m.Variacao.produto_id != exceto_produto_id)
    return db.scalar(consulta)
