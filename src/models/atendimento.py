from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.atendimento import CANAIS_ATENDIMENTO, CANAL_ATENDIMENTO_PADRAO, STATUS_ATENDIMENTO
from src.entities.marca import MARCA_PADRAO, MARCAS
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.cliente import Cliente
    from src.models.loja import Loja
    from src.models.mensagem import Mensagem
    from src.models.pedido import Pedido
    from src.models.tipo_solicitacao import TipoSolicitacao
    from src.models.usuario import Usuario


class Atendimento(Base):
    """Chamado de um cliente (troca, devolução, dúvida...). A equipe responde pelo painel.

    Atendimento de WhatsApp, Instagram ou e-mail (Vulto) pode não ter cliente identificado: fica o
    contato que ele usou, para ligar ao cadastro depois. Sem loja = atendimento central da marca (SAC),
    sem uma venda de loja por trás."""

    __tablename__ = "atendimentos"
    __table_args__ = (
        CheckConstraint(valor_em("status", STATUS_ATENDIMENTO), name="ck_atendimentos_status"),
        CheckConstraint(valor_em("canal", CANAIS_ATENDIMENTO), name="ck_atendimentos_canal"),
        CheckConstraint(valor_em("marca", MARCAS), name="ck_atendimentos_marca"),
        CheckConstraint("cliente_id IS NOT NULL OR contato IS NOT NULL", name="ck_atendimentos_cliente_ou_contato"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    protocolo: Mapped[str] = mapped_column(String(20), unique=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"), index=True)
    # Membro da equipe que cuida do caso
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    tipo_solicitacao_id: Mapped[int] = mapped_column(ForeignKey("tipos_solicitacao.id"))
    status: Mapped[str] = mapped_column(String(20), default="ABERTO")
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"))
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    marca: Mapped[str] = mapped_column(String(10), default=MARCA_PADRAO, server_default=MARCA_PADRAO, index=True)
    canal: Mapped[str] = mapped_column(String(20), default=CANAL_ATENDIMENTO_PADRAO, server_default=CANAL_ATENDIMENTO_PADRAO)
    # Como o cliente apareceu no canal (telefone +55 11 94885-4328, e-mail ou @do Instagram) e o nome que deu
    contato: Mapped[str | None] = mapped_column(String(255), index=True)
    contato_nome: Mapped[str | None] = mapped_column(String(120))
    # Número do pedido que o cliente citou, mesmo quando não foi achado ou não é dele (pedido_id fica nulo)
    pedido_citado: Mapped[str | None] = mapped_column(String(40))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cliente: Mapped[Cliente | None] = relationship(lazy="joined")
    responsavel: Mapped[Usuario | None] = relationship(lazy="joined")
    tipo_solicitacao: Mapped[TipoSolicitacao] = relationship(lazy="joined")
    loja: Mapped[Loja | None] = relationship(lazy="joined")
    pedido: Mapped[Pedido | None] = relationship()
    mensagens: Mapped[list[Mensagem]] = relationship(back_populates="atendimento", order_by="(Mensagem.enviado_em, Mensagem.id)")
