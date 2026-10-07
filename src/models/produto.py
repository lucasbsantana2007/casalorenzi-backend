from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base
from src.entities.produto import ESTACOES, GENEROS
from src.models._restricoes import valor_em

if TYPE_CHECKING:
    from src.models.categoria import Categoria
    from src.models.imagem_produto import ImagemProduto
    from src.models.variacao import Variacao


class Produto(Base):
    __tablename__ = "produtos"
    __table_args__ = (
        CheckConstraint(f"genero IS NULL OR {valor_em('genero', GENEROS)}", name="ck_produtos_genero"),
        CheckConstraint(f"estacao IS NULL OR {valor_em('estacao', ESTACOES)}", name="ck_produtos_estacao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160))
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"))
    preco_base: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # genero/estacao alimentam a vitrine (Masculino, Feminino · Inverno, Verão, Atemporal)
    genero: Mapped[str | None] = mapped_column(String(20))
    estacao: Mapped[str | None] = mapped_column(String(20))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Textos da página do produto na vitrine
    descricao: Mapped[str | None] = mapped_column(Text)
    composicao: Mapped[str | None] = mapped_column(Text)
    cuidados: Mapped[str | None] = mapped_column(Text)
    # Removido do catálogo pelo Administrador: some da loja, do painel e do estoque, mas continua
    # no banco porque pedidos, vendas e movimentações antigos apontam para as variações dele
    removido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    categoria: Mapped[Categoria] = relationship(lazy="joined")
    variacoes: Mapped[list[Variacao]] = relationship(back_populates="produto", order_by="Variacao.id")
    # Foto enviada no cadastro (sem ela, o site usa a ilustração do produto)
    imagem: Mapped[ImagemProduto | None] = relationship(
        back_populates="produto", lazy="joined", cascade="all, delete-orphan", uselist=False
    )
