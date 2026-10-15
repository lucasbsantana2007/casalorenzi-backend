from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.fidelidade import CATEGORIAS_FIDELIDADE
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.cliente import Cliente
    from src.models.movimento_pontos import MovimentoPontos


class ContaPontos(Base):
    """Conta do Vulto+ de um cliente (pontos só com CPF; regras em src/entities/fidelidade.py).
    saldo é um cache da soma dos movimentos e nunca fica negativo.
    categoria é a calculada pela regra; categoria_declarada guarda a que veio da planilha da Vulto,
    colocada à mão (texto original)."""

    __tablename__ = "contas_pontos"
    __table_args__ = (
        CheckConstraint("saldo >= 0", name="ck_contas_pontos_saldo"),
        # Nula enquanto não foi calculada; o IN do SQL aceita NULL
        CheckConstraint(valor_em("categoria", CATEGORIAS_FIDELIDADE), name="ck_contas_pontos_categoria"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), unique=True)
    saldo: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    categoria: Mapped[str | None] = mapped_column(String(10))
    categoria_declarada: Mapped[str | None] = mapped_column(String(40))
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cliente: Mapped[Cliente] = relationship(lazy="joined")
    movimentos: Mapped[list[MovimentoPontos]] = relationship(
        back_populates="conta", order_by="(MovimentoPontos.data, MovimentoPontos.id)"
    )
