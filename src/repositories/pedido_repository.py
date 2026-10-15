from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src import models as m


def com_itens():
    return select(m.Pedido).options(selectinload(m.Pedido.itens))


def obter(db: Session, pedido_id: int, travar: bool = False) -> m.Pedido | None:
    """travar=True bloqueia o pedido até o fim da transação (ex.: duas devoluções simultâneas do mesmo item)."""
    if travar:
        return db.get(m.Pedido, pedido_id, with_for_update={"of": m.Pedido})
    return db.get(m.Pedido, pedido_id)


def do_cliente(db: Session, cliente_id: int) -> list[m.Pedido]:
    return list(db.scalars(com_itens().where(m.Pedido.cliente_id == cliente_id).order_by(m.Pedido.criado_em.desc(), m.Pedido.id)))


def todos(db: Session) -> list[m.Pedido]:
    return list(db.scalars(com_itens()))


def contar_do_cliente(db: Session, cliente_id: int) -> int:
    return db.scalar(select(func.count()).where(m.Pedido.cliente_id == cliente_id))


def listar(db: Session, *, status: str | None = None, loja_id: int | None = None, canal: str | None = None) -> list[m.Pedido]:
    """Mais recentes primeiro."""
    consulta = com_itens().order_by(m.Pedido.criado_em.desc(), m.Pedido.id.desc())
    if status:
        consulta = consulta.where(m.Pedido.status == status)
    if loja_id:
        consulta = consulta.where(m.Pedido.loja_id == loja_id)
    if canal:
        consulta = consulta.where(m.Pedido.canal == canal)
    return list(db.scalars(consulta))


def do_cliente_por_numero(db: Session, cliente_id: int, numero: str) -> m.Pedido | None:
    return db.scalar(com_itens().where(m.Pedido.cliente_id == cliente_id, m.Pedido.numero == numero.strip()))


def reservar_numeracao(db: Session) -> list[str]:
    """Trava a numeração até o fim da transação (dois checkouts simultâneos não pegam o mesmo número)
    e devolve os números já usados."""
    db.execute(select(func.pg_advisory_xact_lock(_TRAVA_NUMERACAO)))
    return list(db.scalars(select(m.Pedido.numero)))


# Chave do advisory lock da numeração de pedidos (qualquer inteiro fixo e exclusivo)
_TRAVA_NUMERACAO = 104820
