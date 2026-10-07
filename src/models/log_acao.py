from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.log import AREAS_LOG
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.usuario import Usuario


class LogAcao(Base):
    """Log de ações da equipe (central administrativa): quem fez o quê, quando e o que mudou.
    Só cresce: nada aqui é editado ou apagado pela aplicação."""

    __tablename__ = "log_acoes"
    __table_args__ = (CheckConstraint(valor_em("area", AREAS_LOG), name="ck_log_acoes_area"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    area: Mapped[str] = mapped_column(String(20), index=True)
    acao: Mapped[str] = mapped_column(String(30))
    descricao: Mapped[str] = mapped_column(Text)
    # [{ "campo": "Preço de venda", "de": "R$ 890,00", "para": "R$ 920,00" }]
    alteracoes: Mapped[list[dict]] = mapped_column(JSON, default=list)
    referencia_tipo: Mapped[str | None] = mapped_column(String(30))
    referencia_id: Mapped[int | None] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    usuario: Mapped[Usuario | None] = relationship(lazy="joined")
