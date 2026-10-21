from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base


class DePara(Base):
    """De onde veio cada registro migrado da Vulto: origem (arquivo ou tabela, ex.:
    "vulto_corrigido.db:vendas") + id_origem (o id ou a chave lá) → tabela_destino + id_destino aqui.

    Um registro de origem vira no máximo um registro em cada tabela de destino; vários registros de
    origem podem virar o mesmo destino (ex.: cadastros duplicados do mesmo CPF, unidos num cliente).
    Também é a chave para a carga não duplicar nada se precisar rodar de novo."""

    __tablename__ = "de_para"
    __table_args__ = (
        UniqueConstraint("origem", "id_origem", "tabela_destino", name="uq_de_para_origem"),
        Index("ix_de_para_destino", "tabela_destino", "id_destino"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    origem: Mapped[str] = mapped_column(String(120))
    id_origem: Mapped[str] = mapped_column(String(120))
    tabela_destino: Mapped[str] = mapped_column(String(40))
    id_destino: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
