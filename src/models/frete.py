from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base


class ConfigFrete(Base):
    """Regras gerais do frete (uma linha só, id 1). Editável em Administração > Frete."""

    __tablename__ = "config_frete"
    __table_args__ = (CheckConstraint("gratis_minimo >= 0", name="ck_config_frete_gratis_minimo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Compras a partir deste valor têm o frete Padrão grátis para o cliente (a loja paga o custo)
    gratis_minimo: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expresso_ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class FreteRegiao(Base):
    """Por região do CEP: quanto o cliente paga (valor), quanto custa para a loja (custo) e o prazo
    em dias úteis, para o Padrão e o Expresso."""

    __tablename__ = "frete_regioes"
    __table_args__ = (
        CheckConstraint(
            "padrao_valor >= 0 AND padrao_custo >= 0 AND expresso_valor >= 0 AND expresso_custo >= 0",
            name="ck_frete_regioes_valores",
        ),
        CheckConstraint("padrao_prazo_dias > 0 AND expresso_prazo_dias > 0", name="ck_frete_regioes_prazos"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    regiao: Mapped[str] = mapped_column(String(20), unique=True)
    nome: Mapped[str] = mapped_column(String(120))
    ordem: Mapped[int] = mapped_column(Integer)
    padrao_valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    padrao_custo: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    padrao_prazo_dias: Mapped[int] = mapped_column(Integer)
    expresso_valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expresso_custo: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expresso_prazo_dias: Mapped[int] = mapped_column(Integer)
