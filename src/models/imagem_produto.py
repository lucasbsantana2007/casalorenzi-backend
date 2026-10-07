from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.anexo import TAMANHO_MAXIMO_ANEXO, TIPOS_ANEXO
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.produto import Produto


class ImagemProduto(Base):
    """Foto do produto enviada no cadastro (uma por produto), servida em GET /api/produtos/{id}/imagem.
    Mesmas regras dos anexos do atendimento: JPG, PNG ou WebP de até 2 MB."""

    __tablename__ = "imagens_produto"
    __table_args__ = (
        CheckConstraint(valor_em("tipo", TIPOS_ANEXO), name="ck_imagens_produto_tipo"),
        CheckConstraint(f"tamanho > 0 AND tamanho <= {TAMANHO_MAXIMO_ANEXO}", name="ck_imagens_produto_tamanho"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), unique=True)
    nome: Mapped[str] = mapped_column(String(255))
    tipo: Mapped[str] = mapped_column(String(30))
    tamanho: Mapped[int] = mapped_column(Integer)
    # deferred: a listagem de produtos não carrega o arquivo, só a rota da imagem
    dados: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    # Entra na URL (?v=) para o navegador buscar a foto nova depois de uma troca
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    produto: Mapped[Produto] = relationship(back_populates="imagem")
