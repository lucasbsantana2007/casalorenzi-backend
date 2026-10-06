from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.papeis import PAPEIS
from src.models._restricoes import valor_em


class Usuario(Base):
    """Equipe com login no painel (ADMINISTRADOR, LOJISTA, OPERADOR). Clientes ficam em `clientes`."""

    __tablename__ = "usuarios"
    __table_args__ = (CheckConstraint(valor_em("papel", PAPEIS), name="ck_usuarios_papel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    papel: Mapped[str] = mapped_column(String(20))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Loja em que o membro da equipe trabalha (nulo para administradores)
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
