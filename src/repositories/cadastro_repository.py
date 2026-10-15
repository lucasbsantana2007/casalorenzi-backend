from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src import models as m
from src.entities.papeis import EQUIPE


def lojas(db: Session, somente_ativas: bool = False) -> list[m.Loja]:
    consulta = select(m.Loja).order_by(m.Loja.id)
    if somente_ativas:
        consulta = consulta.where(m.Loja.ativa.is_(True))
    return list(db.scalars(consulta))


def loja_por_nome(db: Session, nome: str) -> m.Loja | None:
    return db.scalar(select(m.Loja).where(func.lower(m.Loja.nome) == nome.strip().lower()))


def loja(db: Session, loja_id: int) -> m.Loja | None:
    return db.get(m.Loja, loja_id)


def nomes_categorias(db: Session) -> list[str]:
    return list(db.scalars(select(m.Categoria.nome).order_by(m.Categoria.id)))


def categoria_por_nome(db: Session, nome: str) -> m.Categoria | None:
    return db.scalar(select(m.Categoria).where(m.Categoria.nome == nome))


def equipe(db: Session, papel: str | None = None) -> list[m.Usuario]:
    consulta = select(m.Usuario).where(m.Usuario.papel.in_(EQUIPE), m.Usuario.ativo.is_(True)).order_by(m.Usuario.id)
    if papel:
        consulta = consulta.where(m.Usuario.papel == papel)
    return list(db.scalars(consulta))


def tipos_solicitacao(db: Session, ativo: bool | None = None) -> list[m.TipoSolicitacao]:
    consulta = select(m.TipoSolicitacao).order_by(m.TipoSolicitacao.ordem_exibicao, m.TipoSolicitacao.id)
    if ativo is not None:
        consulta = consulta.where(m.TipoSolicitacao.ativo.is_(ativo))
    return list(db.scalars(consulta))


def tipo_solicitacao(db: Session, tipo_id: int) -> m.TipoSolicitacao | None:
    return db.get(m.TipoSolicitacao, tipo_id)
