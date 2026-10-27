from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.fidelidade import MODOS_AVISO
from src.models._restricoes import valor_em


class Sacola(Base):
    """Cópia da sacola do cliente logado (a sacola continua no navegador). Serve para o lembrete de sacola
    abandonada e para a sacola aparecer em outro aparelho. Sacola vazia apaga a linha."""

    __tablename__ = "sacolas"
    __table_args__ = (
        CheckConstraint(f"lembrete_modo IS NULL OR {valor_em('lembrete_modo', MODOS_AVISO)}", name="ck_sacolas_lembrete_modo"),
    )

    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id", ondelete="CASCADE"), primary_key=True)
    # [{"variacaoId": 12, "quantidade": 1}, ...]
    itens: Mapped[list] = mapped_column(JSON, default=list)
    # Última mudança nos itens (o lembrete conta a partir daqui)
    atualizada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Último lembrete enviado (no máximo um por mudança da sacola e um a cada SACOLA_LEMBRETE_INTERVALO_DIAS)
    lembrete_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lembrete_modo: Mapped[str | None] = mapped_column(String(5))
