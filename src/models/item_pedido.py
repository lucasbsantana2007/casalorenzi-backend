from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.devolucao import Devolucao
    from src.models.pedido import Pedido
    from src.models.variacao import Variacao


class ItemPedido(Base):
    __tablename__ = "itens_pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id"))
    quantidade: Mapped[int] = mapped_column(Integer)
    preco_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    pedido: Mapped[Pedido] = relationship(back_populates="itens")
    variacao: Mapped[Variacao] = relationship(lazy="joined")
    devolucoes: Mapped[list[Devolucao]] = relationship(back_populates="item", order_by="Devolucao.id", lazy="selectin")

    @property
    def quantidade_devolvida(self) -> int:
        return sum(d.quantidade for d in self.devolucoes)
