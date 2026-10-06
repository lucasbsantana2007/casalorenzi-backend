from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m


def do_pedido(db: Session, pedido_id: int) -> list[m.Pagamento]:
    return list(db.scalars(select(m.Pagamento).where(m.Pagamento.pedido_id == pedido_id).order_by(m.Pagamento.id)))
