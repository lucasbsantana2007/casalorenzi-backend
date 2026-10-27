from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.assistente import MODOS_RESPOSTA, PAPEIS_MENSAGEM
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.conversa_assistente import ConversaAssistente


class MensagemAssistente(Base):
    """Uma mensagem da conversa com o assistente: do usuário, do assistente ou do sistema (ex.: "o
    cliente adicionou a peça à sacola"). blocos: o que a tela desenha além do texto (cards de produto,
    tabelas, gráficos, botões de ação), montado com o resultado das consultas e nunca pelo modelo."""

    __tablename__ = "mensagens_assistente"
    __table_args__ = (
        CheckConstraint(valor_em("papel", PAPEIS_MENSAGEM), name="ck_mensagens_assistente_papel"),
        # Nulo nas mensagens do usuário e do sistema; o IN do SQL aceita NULL
        CheckConstraint(valor_em("modo", MODOS_RESPOSTA), name="ck_mensagens_assistente_modo"),
        # Reenvio da mesma mensagem (rede instável, clique duplo) não gera outra resposta
        Index("uq_mensagens_assistente_id_cliente", "conversa_id", "id_cliente", unique=True),
        CheckConstraint("avaliacao IN (1, -1)", name="ck_mensagens_assistente_avaliacao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversa_id: Mapped[str] = mapped_column(ForeignKey("conversas_assistente.id", ondelete="CASCADE"), index=True)
    papel: Mapped[str] = mapped_column(String(12))
    conteudo: Mapped[str] = mapped_column(Text, default="", server_default="")
    blocos: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # Como a resposta foi produzida: LLM, REGRAS ou CONTINGENCIA
    modo: Mapped[str | None] = mapped_column(String(14))
    # Identificador que o navegador manda com a mensagem (para não responder duas vezes ao reenvio)
    id_cliente: Mapped[str | None] = mapped_column(String(64))
    # Pergunta do usuário que esta resposta atende (mesma rodada)
    responde_a_id: Mapped[int | None] = mapped_column(ForeignKey("mensagens_assistente.id", ondelete="SET NULL"))
    request_id: Mapped[str | None] = mapped_column(String(32))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Qualidade da resposta (decisões 98 e 99): o verificador de números (CONFERIDA ou CORRIGIDA), os números
    # sem fonte e o texto que o modelo tinha escrito quando foi trocado; se a rodada falhou e se a Lúcia passou o
    # cliente para uma pessoa depois de falhas seguidas. Nulo nas mensagens do usuário e do sistema.
    auditoria: Mapped[dict | None] = mapped_column(JSON)
    # Avaliação do cliente (decisão 101): 1 = ajudou, -1 = não ajudou, com um comentário opcional
    avaliacao: Mapped[int | None] = mapped_column(SmallInteger)
    avaliacao_comentario: Mapped[str | None] = mapped_column(Text)
    avaliada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversa: Mapped[ConversaAssistente] = relationship(back_populates="mensagens")
