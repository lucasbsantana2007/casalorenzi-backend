"""Confere o login antes da rota rodar (autenticação) e o que o papel pode fazer (autorização).

Estar autenticado não significa estar autorizado: toda rota interna declara o módulo que exige.
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.papeis import ACESSO
from src.repositories import usuario_repository
from src.utils.erros import NaoAutenticado, SemPermissao
from src.utils.seguranca import ler_token

_bearer = HTTPBearer(auto_error=False)

MENSAGEM_SESSAO = "Sessão expirada ou inválida. Entre novamente."


def usuario_atual(
    credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> m.Usuario:
    """Usuário dono do token (Authorization: Bearer ...). Token ausente, vencido ou de conta inativa = 401."""
    usuario_id = ler_token(credenciais.credentials) if credenciais else None
    usuario = usuario_repository.por_id(db, usuario_id) if usuario_id else None
    if usuario is None or not usuario.ativo:
        raise NaoAutenticado(MENSAGEM_SESSAO)
    return usuario


def exigir_papel(*papeis: str):
    """Dependência que libera a rota só para os papéis informados."""

    def verificar(usuario: m.Usuario = Depends(usuario_atual)) -> m.Usuario:
        if usuario.papel not in papeis:
            raise SemPermissao("Seu perfil não tem acesso a este recurso.")
        return usuario

    return verificar


def exigir_modulo(modulo: str):
    """Libera a rota para os papéis que acessam o módulo (tabela ACESSO em src/entities/papeis.py)."""
    return exigir_papel(*ACESSO[modulo])
