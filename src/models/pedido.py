from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.pedido import CANAIS, STATUS_PEDIDO, TIPOS_FRETE
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.cliente import Cliente
    from src.models.evento_pedido import EventoPedido
    from src.models.item_pedido import ItemPedido
    from src.models.loja import Loja
    from src.models.pagamento import Pagamento
    from src.models.transferencia import Transferencia


class Pedido(Base):
    """Venda da loja física ou do e-commerce. total = subtotal (itens) + frete_valor."""

    __tablename__ = "pedidos"
    __table_args__ = (
        CheckConstraint(valor_em("status", STATUS_PEDIDO), name="ck_pedidos_status"),
        CheckConstraint(valor_em("canal", CANAIS), name="ck_pedidos_canal"),
        # Nulo na loja física; o IN do SQL aceita NULL
        CheckConstraint(valor_em("frete_tipo", TIPOS_FRETE), name="ck_pedidos_frete_tipo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(30), unique=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    # Loja que vendeu (loja física) ou que expede (e-commerce)
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    canal: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    codigo_rastreio: Mapped[str | None] = mapped_column(String(40))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Frete e endereço de entrega: só e-commerce (nulos na loja física)
    frete_tipo: Mapped[str | None] = mapped_column(String(20))
    frete_valor: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    frete_prazo_dias: Mapped[int | None] = mapped_column(Integer)
    # Quanto o envio custou para a loja (configuração de frete do dia da compra). Só o Administrador vê
    frete_custo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    entrega_cep: Mapped[str | None] = mapped_column(String(8))
    entrega_rua: Mapped[str | None] = mapped_column(String(160))
    entrega_numero: Mapped[str | None] = mapped_column(String(20))
    entrega_complemento: Mapped[str | None] = mapped_column(String(80))
    entrega_bairro: Mapped[str | None] = mapped_column(String(80))
    entrega_cidade: Mapped[str | None] = mapped_column(String(120))
    entrega_uf: Mapped[str | None] = mapped_column(String(2))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    cliente: Mapped[Cliente] = relationship(lazy="joined")
    loja: Mapped[Loja] = relationship(lazy="joined")
    itens: Mapped[list[ItemPedido]] = relationship(back_populates="pedido", order_by="ItemPedido.id")
    pagamentos: Mapped[list[Pagamento]] = relationship(back_populates="pedido", order_by="Pagamento.id", lazy="selectin")
    eventos: Mapped[list[EventoPedido]] = relationship(
        back_populates="pedido", order_by="(EventoPedido.criado_em, EventoPedido.id)"
    )
    # Transferências automáticas criadas para juntar as peças na loja de expedição
    transferencias: Mapped[list[Transferencia]] = relationship(back_populates="pedido", order_by="Transferencia.id")
