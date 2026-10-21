from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base


class Fornecedor(Base):
    """Fornecedor das peças (ex.: Malharia Serra Azul, Jeans Rio Claro). Um nome por fornecedor:
    as grafias diferentes das notas ("serra azul", "MALHARIA SERRA AZUL LTDA") são o mesmo."""

    __tablename__ = "fornecedores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), unique=True)
