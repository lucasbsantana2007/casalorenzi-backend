"""Hash de senhas e tokens JWT. Senha nunca é guardada em texto puro: só o hash (bcrypt)."""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from src.config.settings import JWT_EXPIRA_HORAS, JWT_SECRET

ALGORITMO = "HS256"


def gerar_hash(segredo: str) -> str:
    return bcrypt.hashpw(segredo.encode(), bcrypt.gensalt()).decode()


def confere_hash(segredo: str, segredo_hash: str | None) -> bool:
    if not segredo_hash:
        return False
    try:
        return bcrypt.checkpw(segredo.encode(), segredo_hash.encode())
    except ValueError:
        return False


def criar_token(usuario_id: int, papel: str) -> str:
    momento = datetime.now(UTC)
    payload = {"sub": str(usuario_id), "papel": papel, "iat": momento, "exp": momento + timedelta(hours=JWT_EXPIRA_HORAS)}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITMO)


def ler_token(token: str) -> int | None:
    """Id do usuário do token, ou None se a assinatura ou a validade não conferem."""
    try:
        return int(jwt.decode(token, JWT_SECRET, algorithms=[ALGORITMO])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
