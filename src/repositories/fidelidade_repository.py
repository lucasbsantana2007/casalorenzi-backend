"""Extrato de pontos do Vulto+."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m


def travar_cliente(db: Session, cliente_id: int) -> None:
    """Trava o cliente até o fim da transação: dois checkouts ao mesmo tempo não gastam o mesmo saldo."""
    db.execute(select(m.Cliente.id).where(m.Cliente.id == cliente_id).with_for_update())


def saldo(db: Session, cliente_id: int) -> int:
    ultimo = db.scalar(
        select(m.MovimentoPontos.saldo_resultante)
        .where(m.MovimentoPontos.cliente_id == cliente_id)
        .order_by(m.MovimentoPontos.id.desc())
        .limit(1)
    )
    return ultimo or 0


def extrato(db: Session, cliente_id: int, limite: int = 100) -> list[m.MovimentoPontos]:
    """Mais recente primeiro."""
    return list(
        db.scalars(
            select(m.MovimentoPontos)
            .where(m.MovimentoPontos.cliente_id == cliente_id)
            .order_by(m.MovimentoPontos.id.desc())
            .limit(limite)
        )
    )


def resgatado_no_pedido(db: Session, pedido_id: int) -> int:
    """Pontos usados no pedido (positivo)."""
    quantidades = db.scalars(
        select(m.MovimentoPontos.quantidade).where(m.MovimentoPontos.pedido_id == pedido_id, m.MovimentoPontos.tipo == "RESGATE")
    )
    return -sum(quantidades)
