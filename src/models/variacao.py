from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.produto import Produto


class Variacao(Base):
    """SKU: combinação de produto + tamanho + cor."""

    __tablename__ = "variacoes"
    __table_args__ = (CheckConstraint("preco_custo IS NULL OR preco_custo >= 0", name="ck_variacoes_preco_custo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    tamanho: Mapped[str] = mapped_column(String(20))
    cor: Mapped[str] = mapped_column(String(40))
    # Quanto a peça custa para a loja. Só o Administrador vê (margem no cadastro e no financeiro)
    preco_custo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    produto: Mapped[Produto] = relationship(back_populates="variacoes")
