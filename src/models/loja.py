from __future__ import annotations

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base


class Loja(Base):
    """Loja física. endereco, telefone e horarios aparecem na página Lojas do site.
    Loja inativa sai do site e da expedição, mas mantém o histórico."""

    __tablename__ = "lojas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), unique=True)
    cidade: Mapped[str] = mapped_column(String(120))
    uf: Mapped[str] = mapped_column(String(2))
    endereco: Mapped[str] = mapped_column(String(255), default="", server_default="")
    telefone: Mapped[str] = mapped_column(String(30), default="", server_default="")
    # Uma linha por texto, ex.: "Segunda a sábado: 10:00–22:00"
    horarios: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
