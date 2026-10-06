from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.loja import Loja
    from src.models.variacao import Variacao


class Estoque(Base):
    """Saldo de uma variação em uma loja. A quantidade é sempre o resultado das movimentações."""

    __tablename__ = "estoques"
    __table_args__ = (UniqueConstraint("loja_id", "variacao_id", name="uq_estoques_loja_variacao"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"), index=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id"), index=True)
    quantidade: Mapped[int] = mapped_column(Integer, default=0)
    quantidade_min: Mapped[int] = mapped_column(Integer, default=2)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    loja: Mapped[Loja] = relationship(lazy="joined")
    variacao: Mapped[Variacao] = relationship(lazy="joined")
