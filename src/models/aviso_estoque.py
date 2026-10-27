from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.fidelidade import MODOS_AVISO
from src.models._restricoes import valor_em


class AvisoEstoque(Base):
    """ "Avise-me quando chegar": o cliente pede para saber quando uma peça esgotada (cor e tamanho) voltar ao site.
    Fica pendente até o e-mail sair (avisado_em). Um pedido pendente por cliente e peça (índice único parcial);
    depois de avisado, o cliente pode pedir de novo."""

    __tablename__ = "avisos_estoque"
    __table_args__ = (
        Index(
            "uq_avisos_estoque_pendente",
            "cliente_id",
            "variacao_id",
            unique=True,
            postgresql_where=text("avisado_em IS NULL"),
        ),
        CheckConstraint(f"modo IS NULL OR {valor_em('modo', MODOS_AVISO)}", name="ck_avisos_estoque_modo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id", ondelete="CASCADE"), index=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id", ondelete="CASCADE"), index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Preenchidos quando o e-mail sai (no modo TESTE, email é o do time)
    avisado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    modo: Mapped[str | None] = mapped_column(String(5))
    email: Mapped[str | None] = mapped_column(String(255))
