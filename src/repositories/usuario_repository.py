from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src import models as m


def por_id(db: Session, usuario_id: int) -> m.Usuario | None:
    return db.get(m.Usuario, usuario_id)


def por_email(db: Session, email: str) -> m.Usuario | None:
    return db.scalar(select(m.Usuario).where(func.lower(m.Usuario.email) == email.strip().lower()))


def todos(db: Session) -> list[m.Usuario]:
    return list(db.scalars(select(m.Usuario).order_by(m.Usuario.id)))


def administradores_ativos(db: Session, exceto_id: int | None = None) -> int:
    consulta = select(func.count(m.Usuario.id)).where(m.Usuario.papel == "ADMINISTRADOR", m.Usuario.ativo.is_(True))
    if exceto_id is not None:
        consulta = consulta.where(m.Usuario.id != exceto_id)
    return db.scalar(consulta) or 0


def ativos_por_loja(db: Session) -> dict[int, int]:
    consulta = (
        select(m.Usuario.loja_id, func.count(m.Usuario.id))
        .where(m.Usuario.ativo.is_(True), m.Usuario.loja_id.is_not(None))
        .group_by(m.Usuario.loja_id)
    )
    return dict(db.execute(consulta).all())
