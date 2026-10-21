from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.fidelidade import TIPOS_MOVIMENTO_PONTOS, restricao_sinal
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.cliente import Cliente
    from src.models.loja import Loja
    from src.models.pedido import Pedido


class MovimentoPontos(Base):
    """Extrato do Vulto+ (regras em src/entities/fidelidade.py). Quantidade com sinal: positiva entra,
    negativa sai. O saldo do cliente é o saldo_resultante do último movimento (por criado_em e id),
    que o banco não deixa ficar negativo. O passivo de pontos numa data é a soma dos saldos nela."""

    __tablename__ = "movimentos_pontos"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_MOVIMENTO_PONTOS), name="ck_movimentos_pontos_tipo"),
        CheckConstraint(restricao_sinal(), name="ck_movimentos_pontos_sinal"),
        CheckConstraint("saldo_resultante >= 0", name="ck_movimentos_pontos_saldo"),
        CheckConstraint("valor_desconto IS NULL OR valor_desconto >= 0", name="ck_movimentos_pontos_valor"),
        # Extrato do cliente em ordem e o último saldo de cada um
        Index("ix_movimentos_pontos_cliente_data", "cliente_id", "criado_em", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    tipo: Mapped[str] = mapped_column(String(20))
    quantidade: Mapped[int] = mapped_column(Integer)
    saldo_resultante: Mapped[int] = mapped_column(Integer)
    # Crédito: quando esses pontos vencem (12 meses depois de ganhos)
    vence_em: Mapped[date | None] = mapped_column(Date)
    # Compra que gerou o crédito ou em que o resgate virou desconto
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"), index=True)
    # Onde aconteceu (resgate anotado no balcão de uma loja, por exemplo)
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    # Resgate: o desconto dado em reais. Guardado como foi dado: na Vulto, 420 resgates usaram a taxa
    # antiga (R$ 10 por 100 pontos em vez de R$ 5, decisão 49), e corrigir esconderia a perda
    valor_desconto: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # De onde veio e por quê (ex.: "saldo da planilha congelado em 01/01/2025", "cortesia reclamação insta")
    obs: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Quando o movimento aconteceu (a compra, o resgate, o vencimento)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    cliente: Mapped[Cliente] = relationship(lazy="joined")
    pedido: Mapped[Pedido | None] = relationship()
    loja: Mapped[Loja | None] = relationship()
