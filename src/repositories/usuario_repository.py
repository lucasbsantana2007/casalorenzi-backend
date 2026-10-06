from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src import models as m


def por_id(db: Session, usuario_id: int) -> m.Usuario | None:
    return db.get(m.Usuario, usuario_id)


def por_email(db: Session, email: str) -> m.Usuario | None:
    return db.scalar(select(m.Usuario).where(func.lower(m.Usuario.email) == email.strip().lower()))
