"""Alertas operacionais e o log das automações."""

from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src import models as m
from src.entities.assistente import ABERTO


def listar(
    db: Session,
    *,
    tipos: list[str] | None = None,
    status: str | None = ABERTO,
    marca: str | None = None,
    loja_id: int | None = None,
    limite: int = 200,
) -> list[m.Alerta]:
    """Mais graves e mais recentes primeiro. marca: os da marca e os do grupo (sem marca)."""
    ordem_severidade = {"ALTA": 0, "MEDIA": 1, "BAIXA": 2}
    consulta = select(m.Alerta).order_by(m.Alerta.atualizado_em.desc(), m.Alerta.id.desc())
    if tipos is not None:
        consulta = consulta.where(m.Alerta.tipo.in_(tipos))
    if status:
        consulta = consulta.where(m.Alerta.status == status)
    if marca:
        consulta = consulta.where((m.Alerta.marca == marca) | (m.Alerta.marca.is_(None)))
    if loja_id:
        consulta = consulta.where(m.Alerta.loja_id == loja_id)
    alertas = list(db.scalars(consulta.limit(limite)))
    return sorted(alertas, key=lambda a: (a.status != ABERTO, ordem_severidade.get(a.severidade, 3)))


def obter(db: Session, alerta_id: int, travar: bool = False) -> m.Alerta | None:
    if travar:
        return db.get(m.Alerta, alerta_id, with_for_update={"of": m.Alerta})
    return db.get(m.Alerta, alerta_id)


def abertos_do_tipo(db: Session, tipo: str) -> dict[str, m.Alerta]:
    """Alertas abertos do tipo, pela chave da situação (cada situação tem no máximo um aberto)."""
    return {a.chave: a for a in db.scalars(select(m.Alerta).where(m.Alerta.tipo == tipo, m.Alerta.status == ABERTO))}


def contagem_abertos(db: Session) -> dict[tuple[str, str | None], int]:
    """(tipo, marca) -> quantidade de alertas abertos."""
    linhas = db.execute(
        select(m.Alerta.tipo, m.Alerta.marca, func.count())
        .where(m.Alerta.status == ABERTO)
        .group_by(m.Alerta.tipo, m.Alerta.marca)
    )
    return {(tipo, marca): int(total) for tipo, marca, total in linhas}


# ---------- Execuções ----------


def travar_automacao(db: Session, automacao: str) -> bool:
    """Trava da automação até o fim da transação (pg_try_advisory_xact_lock): False se outra execução da
    mesma automação está rodando agora, em qualquer processo ou servidor."""
    return bool(db.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:chave))"), {"chave": f"automacao:{automacao}"}))


def ultima_execucao(db: Session, automacao: str, status: str | None = None) -> m.ExecucaoAutomacao | None:
    consulta = select(m.ExecucaoAutomacao).where(m.ExecucaoAutomacao.automacao == automacao)
    if status:
        consulta = consulta.where(m.ExecucaoAutomacao.status == status)
    return db.scalar(consulta.order_by(m.ExecucaoAutomacao.iniciada_em.desc(), m.ExecucaoAutomacao.id.desc()).limit(1))


def execucoes(db: Session, limite: int = 50) -> list[m.ExecucaoAutomacao]:
    consulta = select(m.ExecucaoAutomacao).order_by(m.ExecucaoAutomacao.iniciada_em.desc(), m.ExecucaoAutomacao.id.desc())
    return list(db.scalars(consulta.limit(limite)))


def terminada_desde(db: Session, automacao: str, desde: datetime) -> bool:
    """Alguma execução com sucesso da automação terminou depois do instante?"""
    consulta = select(m.ExecucaoAutomacao.id).where(
        m.ExecucaoAutomacao.automacao == automacao,
        m.ExecucaoAutomacao.status == "SUCESSO",
        m.ExecucaoAutomacao.terminada_em >= desde,
    )
    return db.scalar(consulta.limit(1)) is not None
