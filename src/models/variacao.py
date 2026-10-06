from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.produto import Produto


class Variacao(Base):
    """SKU: combinação de produto + tamanho + cor."""

    __tablename__ = "variacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    tamanho: Mapped[str] = mapped_column(String(20))
    cor: Mapped[str] = mapped_column(String(40))

    produto: Mapped[Produto] = relationship(back_populates="variacoes")
