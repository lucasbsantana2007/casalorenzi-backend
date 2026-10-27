from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.assistente import ABERTO, SEVERIDADES, STATUS_ALERTA, TIPOS_ALERTA
from src.entities.marca import MARCAS
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.loja import Loja
    from src.models.usuario import Usuario
    from src.models.variacao import Variacao


class Alerta(Base):
    """Alerta operacional criado pelas automações (estoque baixo, estoque parado, sugestão de
    transferência, pontos a vencer) para a equipe agir. chave identifica a situação (ex.:
    ESTOQUE_BAIXO:loja:variação): a mesma situação nunca tem dois alertas abertos, e quando ela deixa de
    existir a automação resolve o alerta sozinha. Sugestão de transferência nunca é executada sozinha."""

    __tablename__ = "alertas"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_ALERTA), name="ck_alertas_tipo"),
        CheckConstraint(valor_em("status", STATUS_ALERTA), name="ck_alertas_status"),
        CheckConstraint(valor_em("severidade", SEVERIDADES), name="ck_alertas_severidade"),
        CheckConstraint(valor_em("marca", MARCAS), name="ck_alertas_marca"),
        # Uma situação, um alerta aberto (duas execuções ao mesmo tempo não duplicam)
        Index("uq_alertas_chave_aberto", "chave", unique=True, postgresql_where=text("status = 'ABERTO'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30), index=True)
    chave: Mapped[str] = mapped_column(String(160))
    # Nula quando o alerta vale para as duas marcas (os pontos Lupe+ são do grupo)
    marca: Mapped[str | None] = mapped_column(String(10), index=True)
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    variacao_id: Mapped[int | None] = mapped_column(ForeignKey("variacoes.id"))
    titulo: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Números da situação (saldo, mínimo, dias sem venda, quantidade sugerida...)
    dados: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    severidade: Mapped[str] = mapped_column(String(10), default="MEDIA", server_default="MEDIA")
    status: Mapped[str] = mapped_column(String(12), default=ABERTO, server_default=ABERTO, index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Última execução que confirmou a situação
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Quem resolveu ou descartou pelo painel (nulo: a automação viu que a situação acabou)
    resolvido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    loja: Mapped[Loja | None] = relationship(lazy="joined")
    variacao: Mapped[Variacao | None] = relationship(lazy="joined")
    resolvido_por: Mapped[Usuario | None] = relationship(lazy="joined")
