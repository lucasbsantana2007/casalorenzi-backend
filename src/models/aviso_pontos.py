from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.fidelidade import MODOS_AVISO
from src.models._restricoes import valor_em


class AvisoPontos(Base):
    """Aviso por e-mail de pontos Lupe+ a vencer (decisão 82): uma linha por cliente e data de vencimento
    avisada. A chave única garante que rodar a automação de novo nunca manda o mesmo aviso duas vezes.
    Só é gravado depois que o e-mail saiu."""

    __tablename__ = "avisos_pontos"
    __table_args__ = (
        UniqueConstraint("cliente_id", "vencimento", "modo", name="uq_avisos_pontos_cliente_vencimento_modo"),
        CheckConstraint(valor_em("modo", MODOS_AVISO), name="ck_avisos_pontos_modo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id", ondelete="CASCADE"), index=True)
    vencimento: Mapped[date] = mapped_column(Date)
    # Pontos que venciam nessa data quando o aviso saiu
    pontos: Mapped[int] = mapped_column(Integer)
    modo: Mapped[str] = mapped_column(String(5))
    # Para onde o e-mail foi (no modo TESTE, o e-mail do time)
    email: Mapped[str] = mapped_column(String(255))
    # E-mail compartilhado com outra conta: o aviso saiu sem o número
    sem_numeros: Mapped[bool] = mapped_column(default=False)
    enviado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
