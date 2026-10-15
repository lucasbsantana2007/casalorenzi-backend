from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base


class DePara(Base):
    """Rastreio da migração da Vulto: cada registro da plataforma que veio de lá aponta para a origem.

    origem: arquivo ou tabela de onde veio (ex.: "vulto.db:vendas", "catalogo.xlsx:Verão 26");
    id_origem: id ou linha naquela origem. Um registro de origem vira no máximo um registro por
    tabela de destino; vários de origem podem virar o mesmo destino (ex.: clientes duplicados fundidos).
    Também é a chave da idempotência: rodar a migração de novo atualiza em vez de duplicar."""

    __tablename__ = "de_para"
    __table_args__ = (
        UniqueConstraint("origem", "id_origem", "tabela_destino", name="uq_de_para_origem"),
        Index("ix_de_para_destino", "tabela_destino", "id_destino"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    origem: Mapped[str] = mapped_column(String(120))
    id_origem: Mapped[str] = mapped_column(String(80))
    tabela_destino: Mapped[str] = mapped_column(String(40))
    id_destino: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
