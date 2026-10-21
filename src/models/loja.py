from __future__ import annotations

from sqlalchemy import JSON, Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.loja import TIPO_LOJA_PADRAO, TIPOS_LOJA
from src.entities.marca import MARCA_PADRAO, MARCAS
from src.models._restricoes import valor_em


class Loja(Base):
    """Loja física ou centro de distribuição de uma das marcas (src/entities/marca.py e loja.py).
    endereco, telefone e horarios aparecem na página Lojas do site.
    Loja inativa sai do site e da expedição, mas mantém o histórico."""

    __tablename__ = "lojas"
    __table_args__ = (
        CheckConstraint(valor_em("marca", MARCAS), name="ck_lojas_marca"),
        CheckConstraint(valor_em("tipo", TIPOS_LOJA), name="ck_lojas_tipo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), unique=True)
    cidade: Mapped[str] = mapped_column(String(120))
    uf: Mapped[str] = mapped_column(String(2))
    endereco: Mapped[str] = mapped_column(String(255), default="", server_default="")
    telefone: Mapped[str] = mapped_column(String(30), default="", server_default="")
    # Uma linha por texto, ex.: "Segunda a sábado: 10:00–22:00"
    horarios: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    marca: Mapped[str] = mapped_column(String(10), default=MARCA_PADRAO, server_default=MARCA_PADRAO, index=True)
    tipo: Mapped[str] = mapped_column(String(10), default=TIPO_LOJA_PADRAO, server_default=TIPO_LOJA_PADRAO)
