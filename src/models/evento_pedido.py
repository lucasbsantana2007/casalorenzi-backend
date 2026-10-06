from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.pedido import STATUS_PEDIDO
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.pedido import Pedido
    from src.models.usuario import Usuario


class EventoPedido(Base):
    """Histórico do pedido: cada mudança (status, loja de expedição) com quem fez e quando.
    usuario_id nulo = feito pelo sistema (ex.: compra aprovada no checkout)."""

    __tablename__ = "eventos_pedido"
    __table_args__ = (CheckConstraint(valor_em("status", STATUS_PEDIDO), name="ck_eventos_pedido_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    observacao: Mapped[str] = mapped_column(Text, default="", server_default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pedido: Mapped[Pedido] = relationship(back_populates="eventos")
    usuario: Mapped[Usuario | None] = relationship(lazy="joined")
