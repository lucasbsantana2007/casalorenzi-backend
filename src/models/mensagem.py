from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.atendimento import AUTOR_MENSAGEM
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.anexo import Anexo
    from src.models.atendimento import Atendimento
    from src.models.usuario import Usuario


class Mensagem(Base):
    """Conversa do atendimento. autor_id aponta só para a equipe (ATENDENTE); mensagens do
    CLIENTE e do SISTEMA ficam com autor_id nulo (o cliente é o do atendimento)."""

    __tablename__ = "mensagens"
    __table_args__ = (
        CheckConstraint(valor_em("autor_tipo", AUTOR_MENSAGEM), name="ck_mensagens_autor_tipo"),
        CheckConstraint("autor_tipo <> 'CLIENTE' OR autor_id IS NULL", name="ck_mensagens_autor_cliente"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    atendimento_id: Mapped[int] = mapped_column(ForeignKey("atendimentos.id"), index=True)
    autor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    autor_tipo: Mapped[str] = mapped_column(String(20))
    conteudo: Mapped[str] = mapped_column(Text)
    enviado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    atendimento: Mapped[Atendimento] = relationship(back_populates="mensagens")
    autor: Mapped[Usuario | None] = relationship(lazy="joined")
    anexo: Mapped[Anexo | None] = relationship(back_populates="mensagem", uselist=False, lazy="selectin")
