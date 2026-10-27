"""Extrato de pontos do Lupe+ (movimentos_pontos)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m

_ORDEM = (m.MovimentoPontos.criado_em, m.MovimentoPontos.id)


def travar_cliente(db: Session, cliente_id: int) -> None:
    """Trava o cliente até o fim da transação: duas compras ao mesmo tempo não gastam o mesmo saldo."""
    db.execute(select(m.Cliente.id).where(m.Cliente.id == cliente_id).with_for_update())


def saldo(db: Session, cliente_id: int) -> int:
    """saldo_resultante do último movimento (por criado_em e id)."""
    ultimo = db.scalar(
        select(m.MovimentoPontos.saldo_resultante)
        .where(m.MovimentoPontos.cliente_id == cliente_id)
        .order_by(*(c.desc() for c in _ORDEM))
        .limit(1)
    )
    return ultimo or 0


def movimentos(db: Session, cliente_id: int) -> list[m.MovimentoPontos]:
    """Extrato inteiro em ordem cronológica (base do vencimento)."""
    return list(db.scalars(select(m.MovimentoPontos).where(m.MovimentoPontos.cliente_id == cliente_id).order_by(*_ORDEM)))


def extrato(db: Session, cliente_id: int, limite: int = 200) -> list[m.MovimentoPontos]:
    """Mais recente primeiro."""
    return list(
        db.scalars(
            select(m.MovimentoPontos)
            .where(m.MovimentoPontos.cliente_id == cliente_id)
            .order_by(*(c.desc() for c in _ORDEM))
            .limit(limite)
        )
    )


def total_no_pedido(db: Session, pedido_id: int, tipo: str) -> int:
    """Soma das quantidades de um tipo de movimento ligado ao pedido (com sinal)."""
    return sum(
        db.scalars(
            select(m.MovimentoPontos.quantidade).where(m.MovimentoPontos.pedido_id == pedido_id, m.MovimentoPontos.tipo == tipo)
        )
    )


def movimentos_de_todos(db: Session) -> list:
    """(cliente_id, quantidade, vence_em, criado_em) de todo o extrato, em ordem de cliente e data: base dos
    números do programa (pontos válidos, a vencer, clientes por categoria). Só as colunas que a conta usa."""
    mov = m.MovimentoPontos
    return list(db.execute(select(mov.cliente_id, mov.quantidade, mov.vence_em, mov.criado_em).order_by(mov.cliente_id, *_ORDEM)))
