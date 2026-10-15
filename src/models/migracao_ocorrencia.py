from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.connection import Base
from src.entities.migracao import ACOES_OCORRENCIA, DOMINIOS_MIGRACAO, UNIDADES_IMPACTO
from src.models._restricoes import valor_em


class MigracaoOcorrencia(Base):
    """Problema encontrado num dado da Vulto e o que a migração fez com ele. Base do registro de
    decisões (docs/registro_decisoes.md), agregado por codigo_problema.

    Nunca se sobrescreve um valor sem rastro: valor_original guarda o que veio da origem e
    valor_final o que entrou na plataforma (nulo quando o registro foi descartado). impacto, quando
    dá para medir, é o efeito no número final na unidade de impacto_unidade."""

    __tablename__ = "migracao_ocorrencias"
    __table_args__ = (
        CheckConstraint(valor_em("dominio", DOMINIOS_MIGRACAO), name="ck_migracao_ocorrencias_dominio"),
        CheckConstraint(valor_em("acao_tomada", ACOES_OCORRENCIA), name="ck_migracao_ocorrencias_acao"),
        # Nulo quando não há impacto mensurável; o IN do SQL aceita NULL
        CheckConstraint(valor_em("impacto_unidade", UNIDADES_IMPACTO), name="ck_migracao_ocorrencias_unidade"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo_problema: Mapped[str] = mapped_column(String(60), index=True)
    dominio: Mapped[str] = mapped_column(String(20), index=True)
    # Arquivo/tabela/campo (ex.: "vulto.db:vendas.total")
    origem: Mapped[str] = mapped_column(String(160))
    id_origem: Mapped[str | None] = mapped_column(String(80))
    descricao: Mapped[str] = mapped_column(Text)
    acao_tomada: Mapped[str] = mapped_column(String(12))
    valor_original: Mapped[str | None] = mapped_column(Text)
    valor_final: Mapped[str | None] = mapped_column(Text)
    impacto: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    impacto_unidade: Mapped[str | None] = mapped_column(String(10))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
