from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.pagamento import METODOS_PAGAMENTO, PARCELAS_MAX, STATUS_PAGAMENTO
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.pedido import Pedido


class Pagamento(Base):
    """Pagamento de um pedido (regras em src/entities/pagamento.py)."""

    __tablename__ = "pagamentos"
    __table_args__ = (
        CheckConstraint(valor_em("metodo", METODOS_PAGAMENTO), name="ck_pagamentos_metodo"),
        CheckConstraint(valor_em("status", STATUS_PAGAMENTO), name="ck_pagamentos_status"),
        CheckConstraint(f"parcelas BETWEEN 1 AND {PARCELAS_MAX}", name="ck_pagamentos_parcelas"),
        CheckConstraint("valor >= 0", name="ck_pagamentos_valor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    metodo: Mapped[str] = mapped_column(String(20))
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    parcelas: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(20))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pedido: Mapped[Pedido] = relationship(back_populates="pagamentos")
