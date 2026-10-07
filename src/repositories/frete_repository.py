from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m


def config(db: Session, travar: bool = False) -> m.ConfigFrete | None:
    consulta = select(m.ConfigFrete).where(m.ConfigFrete.id == 1)
    if travar:
        consulta = consulta.with_for_update()
    return db.scalar(consulta)


def regioes(db: Session) -> list[m.FreteRegiao]:
    return list(db.scalars(select(m.FreteRegiao).order_by(m.FreteRegiao.ordem)))


def regiao(db: Session, regiao: str) -> m.FreteRegiao | None:
    return db.scalar(select(m.FreteRegiao).where(m.FreteRegiao.regiao == regiao))
