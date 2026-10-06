from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.transferencia import STATUS_TRANSFERENCIA
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.loja import Loja
    from src.models.pedido import Pedido
    from src.models.usuario import Usuario
    from src.models.variacao import Variacao


class Transferencia(Base):
    __tablename__ = "transferencias"
    __table_args__ = (CheckConstraint(valor_em("status", STATUS_TRANSFERENCIA), name="ck_transferencias_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id"))
    loja_origem_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    loja_destino_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    quantidade: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="SOLICITADA")
    solicitante_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    observacao: Mapped[str] = mapped_column(Text, default="")
    # Preenchido nas transferências automáticas do e-commerce (peças que faltam na loja de expedição)
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"), index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recebido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    variacao: Mapped[Variacao] = relationship(lazy="joined")
    loja_origem: Mapped[Loja] = relationship(foreign_keys=[loja_origem_id], lazy="joined")
    loja_destino: Mapped[Loja] = relationship(foreign_keys=[loja_destino_id], lazy="joined")
    solicitante: Mapped[Usuario | None] = relationship(foreign_keys=[solicitante_id], lazy="joined")
    responsavel: Mapped[Usuario | None] = relationship(foreign_keys=[responsavel_id], lazy="joined")
    pedido: Mapped[Pedido | None] = relationship(back_populates="transferencias")
