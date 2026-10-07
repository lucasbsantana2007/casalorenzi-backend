from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m


def listar(db: Session, *, area: str | None = None, usuario_id: int | None = None, limite: int = 2000) -> list[m.LogAcao]:
    consulta = select(m.LogAcao).order_by(m.LogAcao.criado_em.desc(), m.LogAcao.id.desc()).limit(limite)
    if area:
        consulta = consulta.where(m.LogAcao.area == area)
    if usuario_id:
        consulta = consulta.where(m.LogAcao.usuario_id == usuario_id)
    return list(db.scalars(consulta))
