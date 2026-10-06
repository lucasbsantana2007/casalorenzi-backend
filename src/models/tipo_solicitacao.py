from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base


class TipoSolicitacao(Base):
    __tablename__ = "tipos_solicitacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(120))
    categoria: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(String(255), default="")
    exige_venda: Mapped[bool] = mapped_column(Boolean, default=False)
    # Trocas e devoluções entram na taxa de pós-venda do financeiro
    conta_pos_venda: Mapped[str | None] = mapped_column(String(20))
    ordem_exibicao: Mapped[int] = mapped_column(Integer, default=0)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
