from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.cliente import Cliente
    from src.models.usuario import Usuario


class TokenSenha(Base):
    """Link de "esqueci a senha" enviado por e-mail: uso único (usado_em) e com validade (expira_em).
    Serve para a equipe (usuario_id) ou para um cliente (cliente_id): sempre exatamente um dos dois."""

    __tablename__ = "tokens_senha"
    __table_args__ = (CheckConstraint("(usuario_id IS NULL) <> (cliente_id IS NULL)", name="ck_tokens_senha_dono"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"), index=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    usado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usuario: Mapped[Usuario | None] = relationship(lazy="joined")
    cliente: Mapped[Cliente | None] = relationship(lazy="joined")
