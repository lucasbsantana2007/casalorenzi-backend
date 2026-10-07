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
    """papel "CLIENTE" para a conta de um cliente (usuario_id é o id do cliente)."""
    momento = datetime.now(UTC)
    payload = {"sub": str(usuario_id), "papel": papel, "iat": momento, "exp": momento + timedelta(hours=JWT_EXPIRA_HORAS)}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITMO)


def ler_token(token: str) -> tuple[int, str] | None:
    """(id, papel) do token, ou None se a assinatura ou a validade não conferem.
    papel "CLIENTE": o id é de `clientes`; os demais papéis são da equipe (`usuarios`)."""
    try:
        dados = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITMO])
        return int(dados["sub"]), str(dados["papel"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
