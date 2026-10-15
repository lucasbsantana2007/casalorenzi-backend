from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.fidelidade import TIPOS_MOVIMENTO_PONTOS
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.pedido import Pedido


class MovimentoPontos(Base):
    """Extrato do Vulto+. Quantidade com sinal: positiva entra, negativa sai. O saldo do cliente é o
    saldo_resultante do último movimento, que o banco não deixa ficar negativo."""

    __tablename__ = "movimentos_pontos"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_MOVIMENTO_PONTOS), name="ck_movimentos_pontos_tipo"),
        CheckConstraint("quantidade <> 0", name="ck_movimentos_pontos_quantidade"),
        CheckConstraint("saldo_resultante >= 0", name="ck_movimentos_pontos_saldo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    quantidade: Mapped[int] = mapped_column(Integer)
    saldo_resultante: Mapped[int] = mapped_column(Integer)
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"), index=True)
    obs: Mapped[str] = mapped_column(String(255), default="", server_default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    pedido: Mapped[Pedido | None] = relationship(lazy="joined")
