from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.estoque import TIPOS_MOVIMENTACAO
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.estoque import Estoque
    from src.models.usuario import Usuario


class Movimentacao(Base):
    """Histórico de estoque. Quantidade com sinal: positiva entra, negativa sai."""

    __tablename__ = "movimentacoes"
    __table_args__ = (CheckConstraint(valor_em("tipo", TIPOS_MOVIMENTACAO), name="ck_movimentacoes_tipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    estoque_id: Mapped[int] = mapped_column(ForeignKey("estoques.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(30))
    quantidade: Mapped[int] = mapped_column(Integer)
    origem: Mapped[str] = mapped_column(String(255), default="")
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    transferencia_id: Mapped[int | None] = mapped_column(ForeignKey("transferencias.id"))
    saldo_resultante: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    estoque: Mapped[Estoque] = relationship(lazy="joined")
    usuario: Mapped[Usuario | None] = relationship(lazy="joined")
