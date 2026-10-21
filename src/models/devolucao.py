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
    from src.models.variacao import Variacao


class Devolucao(Base):
    """Peças devolvidas (regras em src/entities/devolucao.py). variacao_id é sempre a peça que voltou.

    Na plataforma, toda devolução é de um item de pedido. As da Vulto eram lançadas como uma venda de
    valor negativo e só às vezes citavam a venda original (decisão 12 do registro da Vulto): sem a
    venda original, ficam sem pedido e sem item; com a venda mas sem o item, só com o pedido."""

    __tablename__ = "devolucoes"
    __table_args__ = (
        CheckConstraint("quantidade > 0", name="ck_devolucoes_quantidade"),
        CheckConstraint("valor_devolvido >= 0", name="ck_devolucoes_valor"),
        CheckConstraint("item_pedido_id IS NULL OR pedido_id IS NOT NULL", name="ck_devolucoes_item_do_pedido"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_pedido_id: Mapped[int | None] = mapped_column(ForeignKey("itens_pedido.id"), index=True)
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"), index=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id"), index=True)
    atendimento_id: Mapped[int | None] = mapped_column(ForeignKey("atendimentos.id"))
    # Quem da equipe registrou (nulo nas devoluções da Vulto, que não guardava)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    # Loja em que a peça volta para o estoque
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"), index=True)
    # Movimentação DEVOLUCAO gerada no estoque (rastreabilidade)
    movimentacao_id: Mapped[int | None] = mapped_column(ForeignKey("movimentacoes.id"))
    quantidade: Mapped[int] = mapped_column(Integer)
    valor_devolvido: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    motivo: Mapped[str] = mapped_column(Text, default="")
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    item: Mapped[ItemPedido | None] = relationship(back_populates="devolucoes")
    variacao: Mapped[Variacao] = relationship(lazy="joined")
    pedido: Mapped[Pedido | None] = relationship(lazy="joined")
    atendimento: Mapped[Atendimento | None] = relationship()
    usuario: Mapped[Usuario | None] = relationship(lazy="joined")
    loja: Mapped[Loja] = relationship(lazy="joined")
    movimentacao: Mapped[Movimentacao | None] = relationship()
