"""Cadastros de apoio usados em filtros e formulários."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Categoria, Loja, TipoSolicitacao, Usuario
from app.security import EQUIPE, exigir_papel
from app.views import loja_view, tipo_solicitacao_view, usuario_view

router = APIRouter(tags=["Cadastros"])


@router.get("/lojas")
def listar_lojas(db: Session = Depends(get_db)):
    return [loja_view(loja) for loja in db.scalars(select(Loja).order_by(Loja.id))]


@router.get("/categorias")
def listar_categorias(db: Session = Depends(get_db)) -> list[str]:
    """Lista de nomes, na ordem de cadastro."""
    return list(db.scalars(select(Categoria.nome).order_by(Categoria.id)))


@router.get("/usuarios")
def listar_usuarios(
    papel: Literal["ADMINISTRADOR", "LOJISTA", "OPERADOR"] | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_papel(*EQUIPE)),
):
    """Membros da equipe (clientes não aparecem aqui)."""
    consulta = select(Usuario).where(Usuario.papel.in_(EQUIPE), Usuario.ativo.is_(True)).order_by(Usuario.id)
    if papel:
        consulta = consulta.where(Usuario.papel == papel)
    return [usuario_view(u) for u in db.scalars(consulta)]


@router.get("/tipos-solicitacao")
def listar_tipos_solicitacao(ativo: bool | None = None, db: Session = Depends(get_db)):
    consulta = select(TipoSolicitacao).order_by(TipoSolicitacao.ordem_exibicao, TipoSolicitacao.id)
    if ativo is not None:
        consulta = consulta.where(TipoSolicitacao.ativo.is_(ativo))
    return [tipo_solicitacao_view(t) for t in db.scalars(consulta)]
