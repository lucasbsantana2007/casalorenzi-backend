"""Cadastros de apoio usados em filtros e formulários."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.papeis import EQUIPE
from src.middlewares.autenticacao import exigir_papel
from src.repositories import cadastro_repository
from src.schemas.cadastros import loja_saida, tipo_solicitacao_saida, usuario_saida

router = APIRouter(tags=["Cadastros"])


@router.get("/lojas")
def listar_lojas(db: Session = Depends(get_db)):
    return [loja_saida(loja) for loja in cadastro_repository.lojas(db)]


@router.get("/categorias")
def listar_categorias(db: Session = Depends(get_db)) -> list[str]:
    """Lista de nomes, na ordem de cadastro."""
    return cadastro_repository.nomes_categorias(db)


@router.get("/usuarios")
def listar_usuarios(
    papel: Literal["ADMINISTRADOR", "LOJISTA", "OPERADOR"] | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(exigir_papel(*EQUIPE)),
):
    """Membros da equipe."""
    return [usuario_saida(u) for u in cadastro_repository.equipe(db, papel)]


@router.get("/tipos-solicitacao")
def listar_tipos_solicitacao(ativo: bool | None = None, db: Session = Depends(get_db)):
    return [tipo_solicitacao_saida(t) for t in cadastro_repository.tipos_solicitacao(db, ativo)]
