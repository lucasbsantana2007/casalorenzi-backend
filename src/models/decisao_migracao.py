from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.migracao import AREAS_MIGRACAO, SITUACOES_DECISAO, TIPOS_DECISAO
from src.models._restricoes import valor_em


class DecisaoMigracao(Base):
    """Registro de decisões da migração da Vulto, com as colunas pedidas pela diretoria. numero segue o
    registro da Vulto (migracao/registro_decisoes.md, 1 a 54); as decisões da carga na plataforma
    continuam a numeração."""

    __tablename__ = "decisoes_migracao"
    __table_args__ = (
        CheckConstraint(valor_em("area", AREAS_MIGRACAO), name="ck_decisoes_migracao_area"),
        CheckConstraint(valor_em("tipo", TIPOS_DECISAO), name="ck_decisoes_migracao_tipo"),
        CheckConstraint(valor_em("situacao", SITUACOES_DECISAO), name="ck_decisoes_migracao_situacao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(Integer, unique=True)
    area: Mapped[str] = mapped_column(String(20))
    o_que_encontramos: Mapped[str] = mapped_column(Text)
    # Arquivo / tabela / campo
    onde: Mapped[str] = mapped_column(Text)
    quantos_registros: Mapped[str] = mapped_column(Text)
    o_que_decidimos: Mapped[str] = mapped_column(Text)
    por_que: Mapped[str] = mapped_column(Text)
    impacto: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20))
    situacao: Mapped[str] = mapped_column(String(20), default="APLICADA", server_default="APLICADA")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
