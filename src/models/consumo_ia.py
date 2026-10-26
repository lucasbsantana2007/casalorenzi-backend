from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.assistente import STATUS_CONSUMO, TIPOS_ASSISTENTE
from src.models._restricoes import valor_em


class ConsumoIA(Base):
    """Uma chamada ao modelo de linguagem: tokens que a API informou, custo estimado e duração.
    Fica mesmo depois que a conversa é apagada pela retenção (conversa_id vira nulo): é o histórico de custo."""

    __tablename__ = "consumo_ia"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_ASSISTENTE), name="ck_consumo_ia_tipo"),
        CheckConstraint(valor_em("status", STATUS_CONSUMO), name="ck_consumo_ia_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversa_id: Mapped[str | None] = mapped_column(ForeignKey("conversas_assistente.id", ondelete="SET NULL"), index=True)
    tipo: Mapped[str] = mapped_column(String(12))
    provedor: Mapped[str] = mapped_column(String(20))
    modelo: Mapped[str] = mapped_column(String(60))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saida: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache_leitura: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache_escrita: Mapped[int] = mapped_column(Integer, default=0)
    # Em dólares, pela tabela de src/entities/assistente.py (nulo para modelo fora da tabela)
    custo_estimado: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    duracao_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
