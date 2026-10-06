from sqlalchemy.orm import Session

from src import models as m
from src.repositories import usuario_repository
from src.utils.erros import NaoAutenticado
from src.utils.seguranca import confere_hash, criar_token


def entrar(db: Session, email: str, senha: str) -> tuple[str, m.Usuario]:
    """Confere e-mail e senha e devolve (token, usuário). A mensagem é a mesma para e-mail
    inexistente e senha errada, para não revelar quais e-mails têm conta."""
    usuario = usuario_repository.por_email(db, email)
    if usuario is None or not usuario.ativo or not confere_hash(senha, usuario.senha_hash):
        raise NaoAutenticado("E-mail ou senha incorretos.")
    return criar_token(usuario.id, usuario.papel), usuario
