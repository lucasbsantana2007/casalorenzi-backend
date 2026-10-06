from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.categoria import Categoria
    from src.models.variacao import Variacao


class Produto(Base):
    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160))
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"))
    preco_base: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # genero/estacao alimentam a vitrine (Masculino, Feminino · Inverno, Verão, Atemporal)
    genero: Mapped[str | None] = mapped_column(String(20))
    estacao: Mapped[str | None] = mapped_column(String(20))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Textos da página do produto na vitrine
    descricao: Mapped[str | None] = mapped_column(Text)
    composicao: Mapped[str | None] = mapped_column(Text)
    cuidados: Mapped[str | None] = mapped_column(Text)

    categoria: Mapped[Categoria] = relationship(lazy="joined")
    variacoes: Mapped[list[Variacao]] = relationship(back_populates="produto", order_by="Variacao.id")
