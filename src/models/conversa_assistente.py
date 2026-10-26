from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.assistente import ATIVA, STATUS_CONVERSA, TIPOS_ASSISTENTE
from src.entities.marca import MARCAS
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.mensagem_assistente import MensagemAssistente


class ConversaAssistente(Base):
    """Conversa com um assistente de IA (src/entities/assistente.py).

    CLIENTE: o assistente do site. Sem login, a conversa é do navegador que a abriu: só quem tem a chave
    (devolvida uma vez, guardada aqui só como hash) lê e escreve nela. Com login de cliente, ela passa a
    ser da conta (cliente_id) e só esse cliente a abre.
    GERENCIAL: o copiloto do painel, sempre de um membro da equipe (usuario_id).
    contexto: a memória curta da conversa (última busca, peça em foco, loja em foco), enviada ao modelo
    no lugar do histórico inteiro."""

    __tablename__ = "conversas_assistente"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_ASSISTENTE), name="ck_conversas_assistente_tipo"),
        CheckConstraint(valor_em("status", STATUS_CONVERSA), name="ck_conversas_assistente_status"),
        CheckConstraint(valor_em("marca", MARCAS), name="ck_conversas_assistente_marca"),
        # O copiloto é sempre de alguém da equipe; o assistente do site nunca é
        CheckConstraint(
            "(tipo = 'GERENCIAL' AND usuario_id IS NOT NULL AND cliente_id IS NULL) OR (tipo = 'CLIENTE' AND usuario_id IS NULL)",
            name="ck_conversas_assistente_dono",
        ),
    )

    # uuid4 em hexadecimal: o id público não é sequencial (ninguém adivinha a conversa de outro)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(12))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    # sha256 da chave da conversa (a chave em si só o navegador tem)
    chave_hash: Mapped[str | None] = mapped_column(String(64))
    # Vitrine em que a conversa começou (LORENZI ou VULTO); nula no copiloto
    marca: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(12), default=ATIVA, server_default=ATIVA)
    contexto: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    # Chamado aberto pelo encaminhamento para o atendimento humano
    atendimento_id: Mapped[int | None] = mapped_column(ForeignKey("atendimentos.id"))
    # Copiloto: a primeira pergunta, para a lista de conversas anteriores
    titulo: Mapped[str | None] = mapped_column(String(120))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    atualizada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Depois disso a automação de limpeza apaga a conversa (política de retenção)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    mensagens: Mapped[list[MensagemAssistente]] = relationship(
        back_populates="conversa",
        order_by="(MensagemAssistente.criada_em, MensagemAssistente.id)",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
