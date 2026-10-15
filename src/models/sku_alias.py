from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.variacao import Variacao


class SkuAlias(Base):
    """Outra grafia de um SKU (código curto do CD, digitação do fiscal, minúsculas, espaços...).
    A busca é pelo alias_normalizado; alias guarda a grafia original.

    O mesmo código pode ter sido reaproveitado por outra peça em outra coleção (regra 8 de Compras
    da Vulto): a vigência (valido_de/valido_ate, nulo = sem limite) diz a qual variação ele se
    refere em cada data."""

    __tablename__ = "sku_alias"
    __table_args__ = (
        UniqueConstraint("alias_normalizado", "valido_de", name="uq_sku_alias_vigencia", postgresql_nulls_not_distinct=True),
        CheckConstraint("valido_de IS NULL OR valido_ate IS NULL OR valido_ate >= valido_de", name="ck_sku_alias_vigencia"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id"), index=True)
    alias: Mapped[str] = mapped_column(String(80))
    alias_normalizado: Mapped[str] = mapped_column(String(80), index=True)
    # De onde veio a grafia (ex.: "catalogo.xlsx:Verão 26", "vulto.db:itens_venda")
    origem: Mapped[str] = mapped_column(String(120), default="", server_default="")
    valido_de: Mapped[date | None] = mapped_column(Date)
    valido_ate: Mapped[date | None] = mapped_column(Date)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    variacao: Mapped[Variacao] = relationship(lazy="joined")
