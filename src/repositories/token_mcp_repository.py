"""Tokens pessoais do servidor MCP e a auditoria das chamadas (decisão 106)."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src import models as m


def por_hash(db: Session, hash_: str) -> m.TokenMcp | None:
    return db.scalar(select(m.TokenMcp).where(m.TokenMcp.hash == hash_))


def do_usuario(db: Session, usuario_id: int) -> list[m.TokenMcp]:
    """Todos os tokens da pessoa, os mais novos primeiro (inclusive revogados e vencidos, para o histórico)."""
    return list(
        db.scalars(
            select(m.TokenMcp)
            .where(m.TokenMcp.usuario_id == usuario_id)
            .order_by(m.TokenMcp.criado_em.desc(), m.TokenMcp.id.desc())
        )
    )


def ativos_do_usuario(db: Session, usuario_id: int, momento: datetime) -> int:
    return db.scalar(
        select(func.count())
        .select_from(m.TokenMcp)
        .where(
            m.TokenMcp.usuario_id == usuario_id,
            m.TokenMcp.revogado_em.is_(None),
            m.TokenMcp.expira_em > momento,
        )
    )


def chamadas_por_token(db: Session, token_ids: list[int]) -> dict[int, int]:
    if not token_ids:
        return {}
    linhas = db.execute(
        select(m.ChamadaMcp.token_id, func.count()).where(m.ChamadaMcp.token_id.in_(token_ids)).group_by(m.ChamadaMcp.token_id)
    )
    return {token_id: total for token_id, total in linhas}
