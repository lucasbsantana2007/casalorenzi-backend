from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src import models as m


def obter(db: Session, transferencia_id: int, travar: bool = False) -> m.Transferencia | None:
    if travar:
        return db.get(m.Transferencia, transferencia_id, with_for_update={"of": m.Transferencia})
    return db.get(m.Transferencia, transferencia_id)


def listar(db: Session, status: str | None = None, loja_id: int | None = None) -> list[m.Transferencia]:
    """loja_id: transferências que saem ou chegam na loja."""
    consulta = select(m.Transferencia).order_by(m.Transferencia.criado_em.desc(), m.Transferencia.id)
    if status:
        consulta = consulta.where(m.Transferencia.status == status)
    if loja_id:
        consulta = consulta.where(or_(m.Transferencia.loja_origem_id == loja_id, m.Transferencia.loja_destino_id == loja_id))
    return list(db.scalars(consulta))
