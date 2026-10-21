from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.estoque import TIPOS_MOVIMENTACAO
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.estoque import Estoque
    from src.models.usuario import Usuario


class Movimentacao(Base):
    """Histórico de estoque. Quantidade com sinal: positiva entra, negativa sai.
    criado_em é quando o movimento aconteceu: a posição numa data é a soma até ela."""

    __tablename__ = "movimentacoes"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_MOVIMENTACAO), name="ck_movimentacoes_tipo"),
        CheckConstraint("saldo_resultante >= 0", name="ck_movimentacoes_saldo"),
        CheckConstraint("custo_unitario IS NULL OR custo_unitario >= 0", name="ck_movimentacoes_custo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    estoque_id: Mapped[int] = mapped_column(ForeignKey("estoques.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(30))
    quantidade: Mapped[int] = mapped_column(Integer)
    origem: Mapped[str] = mapped_column(String(255), default="")
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    transferencia_id: Mapped[int | None] = mapped_column(ForeignKey("transferencias.id"))
    # Pedido que tirou (venda, troca) ou devolveu a peça
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"), index=True)
    # Entrada de compra: nota fiscal e custo da peça na nota (base do custo médio)
    nota_fiscal: Mapped[str | None] = mapped_column(String(40))
    custo_unitario: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Quantidade estimada, não contada nem registrada (ex.: saldo inicial reconstruído, avaria estimada)
    estimado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    saldo_resultante: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    estoque: Mapped[Estoque] = relationship(lazy="joined")
    usuario: Mapped[Usuario | None] = relationship(lazy="joined")
