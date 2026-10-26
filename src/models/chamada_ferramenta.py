from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.assistente import MODOS_RESPOSTA
from src.models._restricoes import valor_em


class ChamadaFerramenta(Base):
    """Auditoria: cada consulta que um assistente fez (qual ferramenta, com que parâmetros, se deu certo
    e quanto demorou). Inclui as recusadas: ferramenta inexistente, parâmetro inválido, sem permissão."""

    __tablename__ = "chamadas_ferramenta"
    __table_args__ = (CheckConstraint(valor_em("origem", MODOS_RESPOSTA), name="ck_chamadas_ferramenta_origem"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversa_id: Mapped[str] = mapped_column(ForeignKey("conversas_assistente.id", ondelete="CASCADE"), index=True)
    # A resposta do assistente que usou a consulta
    mensagem_id: Mapped[int | None] = mapped_column(ForeignKey("mensagens_assistente.id", ondelete="CASCADE"), index=True)
    ferramenta: Mapped[str] = mapped_column(String(60))
    # Parâmetros como chegaram (o modelo pode mandar qualquer coisa: fica registrado o que foi pedido)
    argumentos: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    sucesso: Mapped[bool] = mapped_column(Boolean)
    erro: Mapped[str | None] = mapped_column(String(255))
    duracao_ms: Mapped[int] = mapped_column(Integer, default=0)
    # Quem pediu a consulta: o modelo (LLM) ou as regras (REGRAS, CONTINGENCIA)
    origem: Mapped[str] = mapped_column(String(14))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
