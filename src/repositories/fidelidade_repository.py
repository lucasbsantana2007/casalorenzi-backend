"""Consultas do Vulto+: conta e extrato do cliente, movimentos de todas as contas (para o passivo) e o que
a migração registrou como não aplicado pelo sistema da Vulto."""

from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src import models as m


def conta_do_cliente(db: Session, cliente_id: int) -> m.ContaPontos | None:
    return db.scalar(
        select(m.ContaPontos)
        .where(m.ContaPontos.cliente_id == cliente_id)
        .options(selectinload(m.ContaPontos.movimentos).joinedload(m.MovimentoPontos.pedido))
    )


def movimentos_por_conta(db: Session, ate: datetime) -> dict[int, tuple[str | None, list[tuple[datetime, int]]]]:
    """conta_id → (categoria, [(data, quantidade)]) sem os vencimentos, que o passivo recalcula."""
    contas = dict(db.execute(select(m.ContaPontos.id, m.ContaPontos.categoria)).all())
    movimentos: dict[int, list[tuple[datetime, int]]] = defaultdict(list)
    for conta_id, data, quantidade in db.execute(
        select(m.MovimentoPontos.conta_id, m.MovimentoPontos.data, m.MovimentoPontos.quantidade).where(
            m.MovimentoPontos.tipo != "VENCIMENTO", m.MovimentoPontos.data < ate
        )
    ):
        movimentos[conta_id].append((data, quantidade))
    return {conta_id: (contas[conta_id], movs) for conta_id, movs in movimentos.items()}


def impacto_da_migracao(db: Session, codigo: str) -> int | None:
    """Pontos registrados pela migração da fidelidade numa ocorrência (ex.: o bônus Ouro nunca aplicado)."""
    valor = db.scalar(
        select(func.sum(m.MigracaoOcorrencia.impacto)).where(
            m.MigracaoOcorrencia.dominio == "fidelidade", m.MigracaoOcorrencia.codigo_problema == codigo
        )
    )
    return None if valor is None else int(valor)
