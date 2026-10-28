from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

if TYPE_CHECKING:
    from src.models.usuario import Usuario


class TokenMcp(Base):
    """Token pessoal de um membro da equipe para usar o copiloto fora do painel, pelo servidor MCP
    (Claude Code, Claude Desktop, n8n; decisão 106). O token aparece uma vez, ao ser criado: aqui fica só o
    sha256 e o começo (prefixo), para a pessoa reconhecer qual é. Vale até expira_em ou até ser revogado; o
    que ele pode consultar é o que o dono pode no momento da chamada (papel, marca e conta ativa)."""

    __tablename__ = "tokens_mcp"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    # Nome dado pela pessoa, para saber onde o token está em uso (ex.: "Claude Code do notebook")
    nome: Mapped[str] = mapped_column(String(60))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefixo: Mapped[str] = mapped_column(String(16))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ultimo_uso_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    usuario: Mapped[Usuario] = relationship(lazy="joined")


class ChamadaMcp(Base):
    """Auditoria do servidor MCP: cada ferramenta chamada, por qual token, com que parâmetros, se deu certo e
    quanto demorou. Inclui as recusadas (sem permissão, parâmetro inválido, limite de consultas)."""

    __tablename__ = "chamadas_mcp"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens_mcp.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    ferramenta: Mapped[str] = mapped_column(String(60))
    argumentos: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    sucesso: Mapped[bool] = mapped_column(Boolean)
    erro: Mapped[str | None] = mapped_column(String(255))
    duracao_ms: Mapped[int] = mapped_column(Integer, default=0)
    # O app que chamou, como ele se apresenta (clientInfo do MCP): só para leitura humana, não é verificado
    cliente: Mapped[str | None] = mapped_column(String(80))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
