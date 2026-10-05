"""Senhas, tokens JWT e controle de acesso por papel.

As regras de acesso espelham src/utils/permissions.js do frontend:
o frontend esconde menus, mas quem garante a regra é a API.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import JWT_EXPIRA_HORAS, JWT_SECRET
from app.database import get_db
from app.models import Usuario

ALGORITMO = "HS256"

EQUIPE = ("ADMINISTRADOR", "LOJISTA", "OPERADOR")
ACESSO = {
    "dashboard": ("ADMINISTRADOR", "LOJISTA", "OPERADOR"),
    "estoque": ("ADMINISTRADOR", "LOJISTA", "OPERADOR"),
    "produtos": ("ADMINISTRADOR",),
    "transferencias": ("ADMINISTRADOR", "OPERADOR"),
    "atendimento": ("ADMINISTRADOR", "LOJISTA"),
    "financeiro": ("ADMINISTRADOR",),
}

_bearer = HTTPBearer(auto_error=False)


def gerar_hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def senha_confere(senha: str, senha_hash: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode(), senha_hash.encode())
    except ValueError:
        return False


def criar_token(usuario: Usuario) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": str(usuario.id),
        "papel": usuario.papel,
        "iat": agora,
        "exp": agora + timedelta(hours=JWT_EXPIRA_HORAS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITMO)


def usuario_atual(
    credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    nao_autenticado = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Sessão expirada ou inválida. Entre novamente.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credenciais is None:
        raise nao_autenticado
    try:
        payload = jwt.decode(credenciais.credentials, JWT_SECRET, algorithms=[ALGORITMO])
        usuario_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise nao_autenticado from None
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.ativo:
        raise nao_autenticado
    return usuario


def exigir_papel(*papeis: str):
    """Dependência que libera a rota só para os papéis informados."""

    def verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if usuario.papel not in papeis:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu perfil não tem acesso a este recurso.")
        return usuario

    return verificar


def exigir_modulo(modulo: str):
    return exigir_papel(*ACESSO[modulo])


def garantir_acesso_cliente(usuario: Usuario, cliente_id: int) -> None:
    """Cliente só vê os próprios dados; administradores e lojistas veem de qualquer cliente."""
    if usuario.papel == "CLIENTE" and usuario.id != cliente_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")
    if usuario.papel != "CLIENTE" and usuario.papel not in ACESSO["atendimento"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu perfil não tem acesso a este recurso.")
