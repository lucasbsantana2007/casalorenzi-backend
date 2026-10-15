from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.atendimento import STATUS_ATENDIMENTO
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.cliente import Cliente
    from src.models.loja import Loja
    from src.models.mensagem import Mensagem
    from src.models.pedido import Pedido
    from src.models.tipo_solicitacao import TipoSolicitacao
    from src.models.usuario import Usuario


class Atendimento(Base):
    """Chamado de um cliente (troca, devolução, dúvida...). A equipe responde pelo painel."""

    __tablename__ = "atendimentos"
    __table_args__ = (CheckConstraint(valor_em("status", STATUS_ATENDIMENTO), name="ck_atendimentos_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    protocolo: Mapped[str] = mapped_column(String(20), unique=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    # Membro da equipe que cuida do caso
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    tipo_solicitacao_id: Mapped[int] = mapped_column(ForeignKey("tipos_solicitacao.id"))
    status: Mapped[str] = mapped_column(String(20), default="ABERTO")
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"))
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cliente: Mapped[Cliente] = relationship(lazy="joined")
    responsavel: Mapped[Usuario | None] = relationship(lazy="joined")
    tipo_solicitacao: Mapped[TipoSolicitacao] = relationship(lazy="joined")
    loja: Mapped[Loja] = relationship(lazy="joined")
    pedido: Mapped[Pedido | None] = relationship()
    mensagens: Mapped[list[Mensagem]] = relationship(back_populates="atendimento", order_by="(Mensagem.enviado_em, Mensagem.id)")
