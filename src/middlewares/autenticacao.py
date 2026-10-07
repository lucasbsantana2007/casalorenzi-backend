"""Confere o login antes da rota rodar (autenticação) e o que o papel pode fazer (autorização).

Estar autenticado não significa estar autorizado: toda rota interna declara o módulo que exige.
O token diz se a sessão é da equipe (papéis de src/entities/papeis.py) ou de um cliente
(papel "CLIENTE"); as duas nunca se misturam.
"""

from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.papeis import ACESSO, CLIENTE
from src.repositories import cliente_repository, usuario_repository
from src.utils.erros import NaoAutenticado, SemPermissao
from src.utils.seguranca import ler_token

_bearer = HTTPBearer(auto_error=False)

MENSAGEM_SESSAO = "Sessão expirada ou inválida. Entre novamente."


@dataclass
class Sessao:
    """Quem está logado: um membro da equipe ou um cliente (sempre exatamente um dos dois)."""

    usuario: m.Usuario | None = None
    cliente: m.Cliente | None = None


def sessao_atual(
    credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Sessao:
    """Dono do token (Authorization: Bearer ...). Token ausente, vencido ou de conta inexistente = 401."""
    lido = ler_token(credenciais.credentials) if credenciais else None
    if lido is not None:
        conta_id, papel = lido
        if papel == CLIENTE:
            cliente = cliente_repository.por_id(db, conta_id)
            if cliente is not None and cliente.senha_hash:
                return Sessao(cliente=cliente)
        else:
            usuario = usuario_repository.por_id(db, conta_id)
            if usuario is not None and usuario.ativo:
                return Sessao(usuario=usuario)
    raise NaoAutenticado(MENSAGEM_SESSAO)


def usuario_atual(sessao: Sessao = Depends(sessao_atual)) -> m.Usuario:
    """Membro da equipe do token. Token de cliente nas rotas da equipe = 401."""
    if sessao.usuario is None:
        raise NaoAutenticado(MENSAGEM_SESSAO)
    return sessao.usuario


def cliente_atual(sessao: Sessao = Depends(sessao_atual)) -> m.Cliente:
    """Cliente do token. Sem sessão de cliente = 401."""
    if sessao.cliente is None:
        raise NaoAutenticado("Entre na sua conta de cliente para continuar.")
    return sessao.cliente


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


def exigir_cliente_ou_modulo(modulo: str):
    """Libera para qualquer cliente logado ou para a equipe com acesso ao módulo. A rota confere
    que o cliente só mexe no que é dele."""

    def verificar(sessao: Sessao = Depends(sessao_atual)) -> Sessao:
        if sessao.usuario is not None and sessao.usuario.papel not in ACESSO[modulo]:
            raise SemPermissao("Seu perfil não tem acesso a este recurso.")
        return sessao

    return verificar
