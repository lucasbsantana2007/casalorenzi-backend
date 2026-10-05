"""Tabelas do banco. Toda mudança aqui precisa de uma migração Alembic:

    alembic revision --autogenerate -m "descricao da mudanca"
    alembic upgrade head
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Valores aceitos nas colunas de "tipo"/"status" (guardados como texto).
PAPEIS = ("ADMINISTRADOR", "LOJISTA", "OPERADOR", "CLIENTE")
TIPOS_MOVIMENTACAO = ("ENTRADA", "VENDA", "DEVOLUCAO", "AJUSTE", "TRANSFERENCIA_SAIDA", "TRANSFERENCIA_ENTRADA")
STATUS_TRANSFERENCIA = ("SOLICITADA", "EM_TRANSITO", "CONCLUIDA", "CANCELADA")
STATUS_PEDIDO = ("PROCESSANDO", "ENVIADO", "ENTREGUE", "CANCELADO")
CANAIS = ("Loja física", "E-commerce")
STATUS_ATENDIMENTO = ("ABERTO", "EM_ANDAMENTO", "AGUARDANDO_CLIENTE", "CONCLUIDO")
ATENDIMENTO_ABERTO = ("ABERTO", "EM_ANDAMENTO", "AGUARDANDO_CLIENTE")
AUTOR_MENSAGEM = ("CLIENTE", "ATENDENTE", "SISTEMA")


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    lista = ", ".join(f"'{v}'" for v in valores)
    return f"{coluna} IN ({lista})"


class Loja(Base):
    __tablename__ = "lojas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    cidade: Mapped[str] = mapped_column(String(120))
    uf: Mapped[str] = mapped_column(String(2))


class Categoria(Base):
    __tablename__ = "categorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)


class Usuario(Base):
    """Equipe (ADMINISTRADOR, LOJISTA, OPERADOR) e clientes (CLIENTE) ficam na mesma tabela."""

    __tablename__ = "usuarios"
    __table_args__ = (CheckConstraint(_em("papel", PAPEIS), name="ck_usuarios_papel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    papel: Mapped[str] = mapped_column(String(20))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Loja em que o membro da equipe trabalha (nulo para administradores)
    loja_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    # Campos de cliente
    telefone: Mapped[str | None] = mapped_column(String(30))
    cliente_desde: Mapped[date | None] = mapped_column(Date)
    loja_preferida_id: Mapped[int | None] = mapped_column(ForeignKey("lojas.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Produto(Base):
    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160))
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"))
    preco_base: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # genero/estacao alimentam a vitrine (Masculino, Feminino · Inverno, Verão, Atemporal)
    genero: Mapped[str | None] = mapped_column(String(20))
    estacao: Mapped[str | None] = mapped_column(String(20))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    categoria: Mapped[Categoria] = relationship(lazy="joined")
    variacoes: Mapped[list["Variacao"]] = relationship(back_populates="produto", order_by="Variacao.id")


class Variacao(Base):
    """SKU: combinação de produto + tamanho + cor."""

    __tablename__ = "variacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    tamanho: Mapped[str] = mapped_column(String(20))
    cor: Mapped[str] = mapped_column(String(40))

    produto: Mapped[Produto] = relationship(back_populates="variacoes")


class Estoque(Base):
    """Saldo de uma variação em uma loja. A quantidade é sempre o resultado das movimentações."""

    __tablename__ = "estoques"
    __table_args__ = (UniqueConstraint("loja_id", "variacao_id", name="uq_estoques_loja_variacao"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"), index=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id"), index=True)
    quantidade: Mapped[int] = mapped_column(Integer, default=0)
    quantidade_min: Mapped[int] = mapped_column(Integer, default=2)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    loja: Mapped[Loja] = relationship(lazy="joined")
    variacao: Mapped[Variacao] = relationship(lazy="joined")


class Transferencia(Base):
    __tablename__ = "transferencias"
    __table_args__ = (CheckConstraint(_em("status", STATUS_TRANSFERENCIA), name="ck_transferencias_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id"))
    loja_origem_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    loja_destino_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    quantidade: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="SOLICITADA")
    solicitante_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    observacao: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recebido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    variacao: Mapped[Variacao] = relationship(lazy="joined")
    loja_origem: Mapped[Loja] = relationship(foreign_keys=[loja_origem_id], lazy="joined")
    loja_destino: Mapped[Loja] = relationship(foreign_keys=[loja_destino_id], lazy="joined")
    solicitante: Mapped[Usuario | None] = relationship(foreign_keys=[solicitante_id], lazy="joined")
    responsavel: Mapped[Usuario | None] = relationship(foreign_keys=[responsavel_id], lazy="joined")


class Movimentacao(Base):
    """Histórico de estoque. Quantidade com sinal: positiva entra, negativa sai."""

    __tablename__ = "movimentacoes"
    __table_args__ = (CheckConstraint(_em("tipo", TIPOS_MOVIMENTACAO), name="ck_movimentacoes_tipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    estoque_id: Mapped[int] = mapped_column(ForeignKey("estoques.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(30))
    quantidade: Mapped[int] = mapped_column(Integer)
    origem: Mapped[str] = mapped_column(String(255), default="")
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    transferencia_id: Mapped[int | None] = mapped_column(ForeignKey("transferencias.id"))
    saldo_resultante: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    estoque: Mapped[Estoque] = relationship(lazy="joined")
    usuario: Mapped[Usuario | None] = relationship(lazy="joined")


class Pedido(Base):
    __tablename__ = "pedidos"
    __table_args__ = (
        CheckConstraint(_em("status", STATUS_PEDIDO), name="ck_pedidos_status"),
        CheckConstraint(_em("canal", CANAIS), name="ck_pedidos_canal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(30), unique=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    canal: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    codigo_rastreio: Mapped[str | None] = mapped_column(String(40))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    loja: Mapped[Loja] = relationship(lazy="joined")
    itens: Mapped[list["ItemPedido"]] = relationship(back_populates="pedido", order_by="ItemPedido.id")


class ItemPedido(Base):
    __tablename__ = "itens_pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    variacao_id: Mapped[int] = mapped_column(ForeignKey("variacoes.id"))
    quantidade: Mapped[int] = mapped_column(Integer)
    preco_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    pedido: Mapped[Pedido] = relationship(back_populates="itens")
    variacao: Mapped[Variacao] = relationship(lazy="joined")


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


class Atendimento(Base):
    __tablename__ = "atendimentos"
    __table_args__ = (CheckConstraint(_em("status", STATUS_ATENDIMENTO), name="ck_atendimentos_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    protocolo: Mapped[str] = mapped_column(String(20), unique=True)
    solicitante_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    tipo_solicitacao_id: Mapped[int] = mapped_column(ForeignKey("tipos_solicitacao.id"))
    status: Mapped[str] = mapped_column(String(20), default="ABERTO")
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"))
    loja_id: Mapped[int] = mapped_column(ForeignKey("lojas.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    solicitante: Mapped[Usuario] = relationship(foreign_keys=[solicitante_id], lazy="joined")
    responsavel: Mapped[Usuario | None] = relationship(foreign_keys=[responsavel_id], lazy="joined")
    tipo_solicitacao: Mapped[TipoSolicitacao] = relationship(lazy="joined")
    loja: Mapped[Loja] = relationship(lazy="joined")
    pedido: Mapped[Pedido | None] = relationship()
    mensagens: Mapped[list["Mensagem"]] = relationship(
        back_populates="atendimento", order_by="(Mensagem.enviado_em, Mensagem.id)"
    )


class Mensagem(Base):
    __tablename__ = "mensagens"
    __table_args__ = (CheckConstraint(_em("autor_tipo", AUTOR_MENSAGEM), name="ck_mensagens_autor_tipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    atendimento_id: Mapped[int] = mapped_column(ForeignKey("atendimentos.id"), index=True)
    autor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    autor_tipo: Mapped[str] = mapped_column(String(20))
    conteudo: Mapped[str] = mapped_column(Text)
    enviado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    atendimento: Mapped[Atendimento] = relationship(back_populates="mensagens")
    autor: Mapped[Usuario | None] = relationship(lazy="joined")
