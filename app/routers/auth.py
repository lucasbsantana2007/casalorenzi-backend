from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario
from app.schemas import LoginEntrada
from app.security import criar_token, senha_confere, usuario_atual
from app.views import usuario_view

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login")
def login(dados: LoginEntrada, db: Session = Depends(get_db)):
    """Mesmo endpoint para equipe e clientes; o papel define a área de acesso."""
    email = dados.email.strip().lower()
    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email))
    if usuario is None or not usuario.ativo or not senha_confere(dados.senha, usuario.senha_hash):
        raise HTTPException(401, "E-mail ou senha incorretos.")
    return {"token": criar_token(usuario), "usuario": usuario_view(usuario)}


@router.get("/me")
def eu(usuario: Usuario = Depends(usuario_atual)):
    """Dados do usuário do token (útil para validar uma sessão salva)."""
    return usuario_view(usuario)
