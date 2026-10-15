from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.produto import Produto


class Variacao(Base):
    """SKU: combinação de produto + tamanho + cor. Outras grafias do mesmo SKU ficam em sku_alias."""

    __tablename__ = "variacoes"
    __table_args__ = (
        CheckConstraint("preco_custo IS NULL OR preco_custo >= 0", name="ck_variacoes_preco_custo"),
        CheckConstraint("ean IS NULL OR ean ~ '^[0-9]{13}$'", name="ck_variacoes_ean"),
        CheckConstraint("custo_medio IS NULL OR custo_medio >= 0", name="ck_variacoes_custo_medio"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    tamanho: Mapped[str] = mapped_column(String(20))
    cor: Mapped[str] = mapped_column(String(40))
    # Quanto a peça custa para a loja (último custo, a regra de Compras). Só o Administrador vê
    preco_custo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Custo médio ponderado das entradas (a regra do Financeiro); nulo sem entrada com custo
    custo_medio: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Código de barras (EAN-13): identifica a peça (tamanho e cor) e desempata grafias de SKU
    ean: Mapped[str | None] = mapped_column(String(13), unique=True)
    # Variação descontinuada (a cor ou o tamanho saiu de linha); o produto continua se outras vendem
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    produto: Mapped[Produto] = relationship(back_populates="variacoes")
