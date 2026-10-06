from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src import models as m


def com_itens():
    return select(m.Pedido).options(selectinload(m.Pedido.itens))


def obter(db: Session, pedido_id: int, travar: bool = False) -> m.Pedido | None:
    """travar=True bloqueia o pedido até o fim da transação (ex.: duas devoluções simultâneas do mesmo item)."""
    if travar:
        return db.get(m.Pedido, pedido_id, with_for_update={"of": m.Pedido})
    return db.get(m.Pedido, pedido_id)


def do_cliente(db: Session, cliente_id: int) -> list[m.Pedido]:
    return list(db.scalars(com_itens().where(m.Pedido.cliente_id == cliente_id).order_by(m.Pedido.criado_em.desc(), m.Pedido.id)))


def todos(db: Session) -> list[m.Pedido]:
    return list(db.scalars(com_itens()))


def contar_do_cliente(db: Session, cliente_id: int) -> int:
    return db.scalar(select(func.count()).where(m.Pedido.cliente_id == cliente_id))
