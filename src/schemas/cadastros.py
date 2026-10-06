"""Cadastros de apoio reutilizam as saídas de comum (lojas, usuários) e de atendimentos (tipos)."""

from src.schemas.atendimentos import tipo_solicitacao_saida
from src.schemas.comum import loja_saida, usuario_saida

__all__ = ["loja_saida", "tipo_solicitacao_saida", "usuario_saida"]
