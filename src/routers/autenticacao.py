from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import usuario_atual
from src.schemas.autenticacao import LoginEntrada
from src.schemas.comum import usuario_saida
from src.use_cases import autenticacao

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login")
def login(dados: LoginEntrada, db: Session = Depends(get_db)):
    """Login da equipe. Devolve o token JWT para o cabeçalho Authorization: Bearer."""
    token, usuario = autenticacao.entrar(db, dados.email, dados.senha)
    return {"token": token, "usuario": usuario_saida(usuario)}


@router.get("/me")
def eu(usuario: m.Usuario = Depends(usuario_atual)):
    """Dados do usuário do token (útil para validar uma sessão salva)."""
    return usuario_saida(usuario)
