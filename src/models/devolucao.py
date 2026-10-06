from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.atendimento import Atendimento
    from src.models.item_pedido import ItemPedido
    from src.models.loja import Loja
    from src.models.movimentacao import Movimentacao
    from src.models.pedido import Pedido
    from src.models.usuario import Usuario


class Devolucao(Base):
    """Peças devolvidas de um item de pedido (regras em src/entities/devolucao.py)."""

    __tablename__ = "devolucoes"
    __table_args__ = (
        CheckConstraint("quantidade > 0", name="ck_devolucoes_quantidade"),
        CheckConstraint("valor_devolvido >= 0", name="ck_devolucoes_valor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_pedido_id: Mapped[int] = mapped_column(ForeignKey("itens_pedido.id"), index=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    atendimento_id: Mapped[int | None] = mapped_column(ForeignKey("atendimentos.id"))
    # Quem da equipe registrou
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    # Loja em que a peça volta para o estoque
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"), index=True)
    # Movimentação DEVOLUCAO gerada no estoque (rastreabilidade)
    movimentacao_id: Mapped[int | None] = mapped_column(ForeignKey("movimentacoes.id"))
    quantidade: Mapped[int] = mapped_column(Integer)
    valor_devolvido: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    motivo: Mapped[str] = mapped_column(Text, default="")
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    item: Mapped[ItemPedido] = relationship(back_populates="devolucoes")
    pedido: Mapped[Pedido] = relationship(lazy="joined")
    atendimento: Mapped[Atendimento | None] = relationship()
    usuario: Mapped[Usuario] = relationship(lazy="joined")
    loja: Mapped[Loja] = relationship(lazy="joined")
    movimentacao: Mapped[Movimentacao | None] = relationship()
