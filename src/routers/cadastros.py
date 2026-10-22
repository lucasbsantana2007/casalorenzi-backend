"""Cadastros de apoio usados em filtros e formulários."""

from typing import Literal

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from src import models as m
from src.database.connection import get_db
from src.entities.loja import LOJA
from src.entities.marca import GRUPO, MARCA_DO_SITE, marca_do_escopo
from src.entities.papeis import EQUIPE
from src.middlewares.autenticacao import Sessao, escopo_marca, exigir_papel, sessao_opcional
from src.repositories import cadastro_repository
from src.schemas.cadastros import loja_saida, tipo_solicitacao_saida, usuario_saida

router = APIRouter(tags=["Cadastros"])


@router.get("/lojas")
def listar_lojas(
    marca: Literal["LORENZI", "VULTO"] | None = None,
    db: Session = Depends(get_db),
    sessao: Sessao | None = Depends(sessao_opcional),
    x_marca: str | None = Header(default=None, alias="X-Marca"),
):
    """Pública: a página Lojas de cada marca pede a sua (?marca=; sem ela, as da Casa Lorenzi), só lojas
    físicas. A equipe logada recebe todas (as duas marcas e o CD), com marca e tipo, para os filtros do painel."""
    if sessao is not None and sessao.usuario is not None:
        # Equipe: só as lojas da marca dela (o grupo, as duas ou a do seletor do painel)
        escopo = marca_do_escopo(sessao.usuario.marca, x_marca)
        if escopo and marca and marca != escopo:
            return []
        return [loja_saida(loja) for loja in cadastro_repository.lojas(db, marca=escopo or marca)]
    return [loja_saida(loja) for loja in cadastro_repository.lojas(db, marca=marca or MARCA_DO_SITE, tipo=LOJA)]


@router.get("/categorias")
def listar_categorias(db: Session = Depends(get_db)) -> list[str]:
    """Lista de nomes, na ordem de cadastro."""
    return cadastro_repository.nomes_categorias(db)


@router.get("/usuarios")
def listar_usuarios(
    papel: Literal["ADMINISTRADOR", "LOJISTA", "OPERADOR"] | None = None,
    db: Session = Depends(get_db),
    _: m.Usuario = Depends(exigir_papel(*EQUIPE)),
    marca: str | None = Depends(escopo_marca),
):
    """Membros da equipe: os da marca de quem pede e os do grupo (que atendem as duas)."""
    return [usuario_saida(u) for u in cadastro_repository.equipe(db, papel) if marca is None or u.marca in (marca, GRUPO)]


@router.get("/tipos-solicitacao")
def listar_tipos_solicitacao(ativo: bool | None = None, db: Session = Depends(get_db)):
    return [tipo_solicitacao_saida(t) for t in cadastro_repository.tipos_solicitacao(db, ativo)]
