from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.use_cases import dashboard

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/resumo")
def obter_resumo(
    lojaId: int | None = None, db: Session = Depends(get_db), usuario: m.Usuario = Depends(exigir_modulo("dashboard"))
):
    """Indicadores da tela inicial do painel. Lojistas veem sempre a própria loja."""
    return dashboard.resumo(db, usuario, lojaId)
