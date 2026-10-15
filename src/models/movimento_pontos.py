from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.fidelidade import TIPOS_MOVIMENTO_PONTOS, restricao_sinal
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.conta_pontos import ContaPontos
    from src.models.pedido import Pedido


class MovimentoPontos(Base):
    """Extrato do Vulto+. Quantidade com sinal: positiva entra (saldo inicial, crédito), negativa sai
    (resgate, estorno, vencimento); o ajuste aceita os dois. vence_em vale para o que entra
    (validade dos pontos, consumidos do mais antigo para o mais novo)."""

    __tablename__ = "movimentos_pontos"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_MOVIMENTO_PONTOS), name="ck_movimentos_pontos_tipo"),
        CheckConstraint(restricao_sinal(), name="ck_movimentos_pontos_sinal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas_pontos.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    quantidade: Mapped[int] = mapped_column(Integer)
    # Quando aconteceu (a compra, o resgate...); criado_em é quando foi gravado aqui
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    vence_em: Mapped[date | None] = mapped_column(Date)
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"), index=True)
    # De onde veio (ex.: "vulto.db:pontos_mov", "clientes.xlsx:Clientes", "pedido")
    origem: Mapped[str] = mapped_column(String(160), default="", server_default="")
    obs: Mapped[str] = mapped_column(Text, default="", server_default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conta: Mapped[ContaPontos] = relationship(back_populates="movimentos")
    pedido: Mapped[Pedido | None] = relationship()
