from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.token_mcp import TokenMcp


class OAuthCliente(Base):
    """App que se conecta ao servidor MCP pelo login OAuth (decisão 114): o claude.ai, o Claude Desktop...
    Cadastrado sozinho, pelo cadastro automático (DCR) ou pela ficha publicada no domínio dele (CIMD, client_id é
    a URL da ficha). Guarda só o hash do segredo, quando o app usa um."""

    __tablename__ = "oauth_clientes"
    __table_args__ = (
        CheckConstraint("origem IN ('DCR', 'CIMD')", name="ck_oauth_clientes_origem"),
        CheckConstraint(
            "metodo_auth IN ('none', 'client_secret_post', 'client_secret_basic')", name="ck_oauth_clientes_metodo_auth"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255), unique=True)
    nome: Mapped[str] = mapped_column(String(120))
    redirect_uris: Mapped[list] = mapped_column(JSON, default=list)
    metodo_auth: Mapped[str] = mapped_column(String(30), default="none")
    segredo_hash: Mapped[str | None] = mapped_column(String(64))
    origem: Mapped[str] = mapped_column(String(4))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthCodigo(Base):
    """Código de autorização: vale 10 minutos e uma vez só, preso ao app, ao endereço de volta e ao PKCE.
    Usado de novo, a conexão que ele gerou é revogada (sinal de código roubado)."""

    __tablename__ = "oauth_codigos"

    id: Mapped[int] = mapped_column(primary_key=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("oauth_clientes.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    recurso: Mapped[str] = mapped_column(String(255))
    escopo: Mapped[str] = mapped_column(String(100))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    usado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A conexão criada na troca do código
    token_mcp_id: Mapped[int | None] = mapped_column(ForeignKey("tokens_mcp.id", ondelete="SET NULL"))


class OAuthToken(Base):
    """Acesso (curto) e renovação (longa, trocada a cada uso) de uma conexão. A conexão é uma linha de tokens_mcp:
    aparece em Inteligência > Conectar ao Claude, revoga por lá, e a auditoria e o limite de consultas são os
    mesmos do token pessoal. Só o sha256 fica aqui."""

    __tablename__ = "oauth_tokens"
    __table_args__ = (CheckConstraint("tipo IN ('ACESSO', 'RENOVACAO')", name="ck_oauth_tokens_tipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token_mcp_id: Mapped[int] = mapped_column(ForeignKey("tokens_mcp.id", ondelete="CASCADE"), index=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("oauth_clientes.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(9))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    recurso: Mapped[str] = mapped_column(String(255))
    escopo: Mapped[str] = mapped_column(String(100))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conexao: Mapped[TokenMcp] = relationship(lazy="joined")
