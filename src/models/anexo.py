from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.anexo import TAMANHO_MAXIMO_ANEXO, TIPOS_ANEXO
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.mensagem import Mensagem


class Anexo(Base):
    """Imagem anexada a uma mensagem do atendimento (no máximo uma por mensagem)."""

    __tablename__ = "anexos"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_ANEXO), name="ck_anexos_tipo"),
        CheckConstraint(f"tamanho > 0 AND tamanho <= {TAMANHO_MAXIMO_ANEXO}", name="ck_anexos_tamanho"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mensagem_id: Mapped[int] = mapped_column(ForeignKey("mensagens.id"), unique=True)
    nome: Mapped[str] = mapped_column(String(255))
    tipo: Mapped[str] = mapped_column(String(30))
    tamanho: Mapped[int] = mapped_column(Integer)
    # deferred: o arquivo só sai do banco quando alguém lê .dados (detalhe do atendimento)
    dados: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mensagem: Mapped[Mensagem] = relationship(back_populates="anexo")
