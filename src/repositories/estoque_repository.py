from datetime import datetime

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from src import models as m


def obter(db: Session, estoque_id: int, travar: bool = False) -> m.Estoque | None:
    """travar=True bloqueia a linha até o fim da transação (evita duas baixas simultâneas no mesmo saldo)."""
    if travar:
        return db.get(m.Estoque, estoque_id, with_for_update={"of": m.Estoque})
    return db.get(m.Estoque, estoque_id)


def por_loja_e_variacao(db: Session, loja_id: int, variacao_id: int, travar: bool = False) -> m.Estoque | None:
    consulta = select(m.Estoque).where(m.Estoque.loja_id == loja_id, m.Estoque.variacao_id == variacao_id)
    if travar:
        consulta = consulta.with_for_update(of=m.Estoque)
    return db.scalar(consulta)


def listar(
    db: Session,
    *,
    loja_id: int | None = None,
    variacao_id: int | None = None,
    categoria: str | None = None,
    incluir_removidos: bool = False,
) -> list[m.Estoque]:
    """incluir_removidos: só para reconstruir o passado (posição em data); o estoque atual não mostra
    produtos removidos do catálogo."""
    consulta = (
        select(m.Estoque).join(m.Estoque.variacao).join(m.Variacao.produto).join(m.Produto.categoria).order_by(m.Estoque.id)
    )
    if not incluir_removidos:
        consulta = consulta.where(m.Produto.removido_em.is_(None))
    if loja_id:
        consulta = consulta.where(m.Estoque.loja_id == loja_id)
    if variacao_id:
        consulta = consulta.where(m.Estoque.variacao_id == variacao_id)
    if categoria:
        consulta = consulta.where(m.Categoria.nome == categoria)
    return list(db.scalars(consulta))


def da_variacao(db: Session, variacao_id: int) -> list[m.Estoque]:
    return list(db.scalars(select(m.Estoque).where(m.Estoque.variacao_id == variacao_id).order_by(m.Estoque.loja_id)))


def totais_por_variacao(db: Session, variacao_ids: list[int]) -> dict[int, int]:
    """Estoque somado de todas as lojas, por variação."""
    if not variacao_ids:
        return {}
    linhas = db.execute(
        select(m.Estoque.variacao_id, func.coalesce(func.sum(m.Estoque.quantidade), 0))
        .where(m.Estoque.variacao_id.in_(variacao_ids))
        .group_by(m.Estoque.variacao_id)
    )
    return {variacao_id: int(total) for variacao_id, total in linhas}


def saldos_ate(db: Session, momento: datetime) -> dict[int, int]:
    """Saldo de cada item no instante informado, somando o histórico de movimentações."""
    return dict(
        db.execute(
            select(m.Movimentacao.estoque_id, func.sum(m.Movimentacao.quantidade))
            .where(m.Movimentacao.criado_em < momento)
            .group_by(m.Movimentacao.estoque_id)
        ).all()
    )


def listar_movimentacoes(
    db: Session,
    *,
    estoque_id: int | None = None,
    loja_id: int | None = None,
    tipo: str | None = None,
    desde: datetime | None = None,
    ate: datetime | None = None,
    limite: int | None = None,
) -> list[m.Movimentacao]:
    consulta = select(m.Movimentacao).join(m.Movimentacao.estoque).order_by(m.Movimentacao.criado_em.desc(), m.Movimentacao.id)
    if estoque_id:
        consulta = consulta.where(m.Movimentacao.estoque_id == estoque_id)
    if loja_id:
        consulta = consulta.where(m.Estoque.loja_id == loja_id)
    if tipo:
        consulta = consulta.where(m.Movimentacao.tipo == tipo)
    if desde:
        consulta = consulta.where(m.Movimentacao.criado_em >= desde)
    if ate:
        consulta = consulta.where(m.Movimentacao.criado_em < ate)
    if limite:
        consulta = consulta.limit(limite)
    return list(db.scalars(consulta))


def pecas_vendidas_desde(db: Session, momento: datetime, loja_id: int | None = None) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(-m.Movimentacao.quantidade), 0))
        .join(m.Movimentacao.estoque)
        .where(
            m.Movimentacao.tipo == "VENDA",
            m.Movimentacao.criado_em >= momento,
            m.Estoque.loja_id == loja_id if loja_id else true(),
        )
    )
    return int(total)


def pecas_por_loja(db: Session) -> dict[int, int]:
    """Soma das peças em estoque de cada loja."""
    consulta = select(m.Estoque.loja_id, func.coalesce(func.sum(m.Estoque.quantidade), 0)).group_by(m.Estoque.loja_id)
    return {loja_id: int(total) for loja_id, total in db.execute(consulta).all()}
