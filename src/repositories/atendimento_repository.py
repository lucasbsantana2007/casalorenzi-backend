from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from src import models as m
from src.entities.atendimento import EM_ABERTO


def obter(db: Session, atendimento_id: int) -> m.Atendimento | None:
    return db.get(m.Atendimento, atendimento_id)


def listar(
    db: Session,
    *,
    tipo_solicitacao_id: int | None = None,
    loja_id: int | None = None,
    responsavel_id: int | None = None,
    sem_responsavel: bool = False,
) -> list[m.Atendimento]:
    consulta = select(m.Atendimento).order_by(m.Atendimento.atualizado_em.desc(), m.Atendimento.id)
    if tipo_solicitacao_id:
        consulta = consulta.where(m.Atendimento.tipo_solicitacao_id == tipo_solicitacao_id)
    if loja_id:
        consulta = consulta.where(m.Atendimento.loja_id == loja_id)
    if sem_responsavel:
        consulta = consulta.where(m.Atendimento.responsavel_id.is_(None))
    elif responsavel_id:
        consulta = consulta.where(m.Atendimento.responsavel_id == responsavel_id)
    return list(db.scalars(consulta))


def em_aberto(db: Session, loja_id: int | None = None) -> list[m.Atendimento]:
    return list(
        db.scalars(
            select(m.Atendimento)
            .where(m.Atendimento.status.in_(EM_ABERTO), m.Atendimento.loja_id == loja_id if loja_id else true())
            .order_by(m.Atendimento.id)
        )
    )


def todos(db: Session) -> list[m.Atendimento]:
    return list(db.scalars(select(m.Atendimento)))


def do_cliente(db: Session, cliente_id: int) -> list[m.Atendimento]:
    return list(
        db.scalars(
            select(m.Atendimento)
            .where(m.Atendimento.cliente_id == cliente_id)
            .order_by(m.Atendimento.criado_em.desc(), m.Atendimento.id)
        )
    )


def contar_do_cliente(db: Session, cliente_id: int) -> int:
    return db.scalar(select(func.count()).where(m.Atendimento.cliente_id == cliente_id))


def ultimas_mensagens(db: Session, atendimento_ids: list[int]) -> dict[int, m.Mensagem]:
    """Última mensagem de cada atendimento, numa única consulta."""
    if not atendimento_ids:
        return {}
    ordem = (
        func.row_number()
        .over(partition_by=m.Mensagem.atendimento_id, order_by=(m.Mensagem.enviado_em.desc(), m.Mensagem.id.desc()))
        .label("ordem")
    )
    sub = select(m.Mensagem.id, ordem).where(m.Mensagem.atendimento_id.in_(atendimento_ids)).subquery()
    mensagens = db.scalars(select(m.Mensagem).join(sub, sub.c.id == m.Mensagem.id).where(sub.c.ordem == 1))
    return {msg.atendimento_id: msg for msg in mensagens}
