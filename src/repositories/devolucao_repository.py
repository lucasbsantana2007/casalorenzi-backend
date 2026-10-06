from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src import models as m


def obter(db: Session, devolucao_id: int) -> m.Devolucao | None:
    return db.get(m.Devolucao, devolucao_id)


def listar(
    db: Session,
    *,
    desde: datetime | None = None,
    ate: datetime | None = None,
    loja_id: int | None = None,
    pedido_id: int | None = None,
) -> list[m.Devolucao]:
    """loja_id: loja em que as peças voltaram para o estoque."""
    consulta = select(m.Devolucao).order_by(m.Devolucao.criada_em.desc(), m.Devolucao.id.desc())
    if desde:
        consulta = consulta.where(m.Devolucao.criada_em >= desde)
    if ate:
        consulta = consulta.where(m.Devolucao.criada_em < ate)
    if loja_id:
        consulta = consulta.where(m.Devolucao.loja_id == loja_id)
    if pedido_id:
        consulta = consulta.where(m.Devolucao.pedido_id == pedido_id)
    return list(db.scalars(consulta))


def devolvido_por_item(db: Session, pedido_id: int) -> dict[int, int]:
    """Quantidade já devolvida de cada item do pedido (item_pedido_id → peças)."""
    linhas = db.execute(
        select(m.Devolucao.item_pedido_id, func.sum(m.Devolucao.quantidade))
        .where(m.Devolucao.pedido_id == pedido_id)
        .group_by(m.Devolucao.item_pedido_id)
    )
    return {item_id: int(total) for item_id, total in linhas}
