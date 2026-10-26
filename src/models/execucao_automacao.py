from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.assistente import AUTOMACOES, STATUS_EXECUCAO
from src.models._restricoes import valor_em


class ExecucaoAutomacao(Base):
    """Log de cada execução de uma automação: quando, quem disparou (nulo = agendador/linha de comando),
    o resultado e quantos alertas criou, atualizou e resolveu. IGNORADA: outra execução da mesma
    automação estava rodando ou tinha acabado de rodar."""

    __tablename__ = "execucoes_automacao"
    __table_args__ = (
        CheckConstraint(valor_em("automacao", AUTOMACOES), name="ck_execucoes_automacao_automacao"),
        CheckConstraint(valor_em("status", STATUS_EXECUCAO), name="ck_execucoes_automacao_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    automacao: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(14))
    iniciada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    terminada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criados: Mapped[int] = mapped_column(Integer, default=0)
    atualizados: Mapped[int] = mapped_column(Integer, default=0)
    resolvidos: Mapped[int] = mapped_column(Integer, default=0)
    # Resumo do resultado ou do erro (sem dado pessoal nem detalhe interno)
    detalhe: Mapped[str] = mapped_column(Text, default="", server_default="")
    disparada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
