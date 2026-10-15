from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.middlewares.autenticacao import exigir_modulo
from src.use_cases import financeiro

router = APIRouter(prefix="/financeiro", tags=["Financeiro"])


@router.get("/resumo")
def obter_resumo(
    de: str | None = None,
    ate: str | None = None,
    comparar: Literal["anterior", "ano", "nenhum"] = "anterior",
    agrupar: Literal["dia", "semana", "mes"] = "dia",
    lojas: str | None = None,
    canais: str | None = None,
    categorias: str | None = None,
    generos: str | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(exigir_modulo("financeiro")),
):
    """Filtros em listas separadas por vírgula (ex.: lojas=1,3&canais=E-commerce)."""
    return financeiro.resumo(
        db, de=de, ate=ate, comparar=comparar, agrupar=agrupar, lojas=lojas, canais=canais, categorias=categorias, generos=generos
    )
