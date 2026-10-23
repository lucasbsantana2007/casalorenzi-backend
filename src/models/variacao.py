from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.produto import STATUS_VARIACAO, STATUS_VARIACAO_PADRAO, ean_interno
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.produto import Produto


class Variacao(Base):
    """SKU: combinação de produto + tamanho + cor."""

    __tablename__ = "variacoes"
    __table_args__ = (
        CheckConstraint("preco_custo IS NULL OR preco_custo >= 0", name="ck_variacoes_preco_custo"),
        CheckConstraint("preco IS NULL OR preco >= 0", name="ck_variacoes_preco"),
        CheckConstraint("ean IS NULL OR ean ~ '^[0-9]{13}$'", name="ck_variacoes_ean"),
        CheckConstraint(valor_em("status", STATUS_VARIACAO), name="ck_variacoes_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    tamanho: Mapped[str] = mapped_column(String(20))
    cor: Mapped[str] = mapped_column(String(40))
    # Quanto a peça custa para a loja (último custo de nota). Só o Administrador vê (margem no cadastro e no financeiro)
    preco_custo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Sem nota fiscal do SKU, o custo foi estimado (mesmo modelo e cor, % da categoria...): decisões do catálogo e 70
    custo_estimado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Preço próprio do SKU quando difere do preço do produto (Vulto: peças da lista de 2024 com o último
    # preço vendido, decisão 39). Nulo = vale o preco_base do produto
    preco: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Código de barras (EAN-13). Começado em 2 = código interno provisório (src/entities/produto.py)
    ean: Mapped[str | None] = mapped_column(String(13), unique=True)
    # Código do SKU no CD e nas etiquetas (Vulto: CAL001V38)
    codigo_cd: Mapped[str | None] = mapped_column(String(20), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_VARIACAO_PADRAO, server_default=STATUS_VARIACAO_PADRAO)
    # O que o time anotou no cadastro (preço antigo e data da aprovação, custo antigo...)
    observacao: Mapped[str | None] = mapped_column(Text)

    produto: Mapped[Produto] = relationship(back_populates="variacoes")

    @property
    def preco_vigente(self) -> Decimal:
        return self.preco if self.preco is not None else self.produto.preco_base

    @property
    def ean_provisorio(self) -> bool:
        return ean_interno(self.ean)
