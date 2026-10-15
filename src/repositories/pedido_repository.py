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


def listar(
    db: Session, *, status: str | None = None, loja_id: int | None = None, canal: str | None = None, marca: str | None = None
) -> list[m.Pedido]:
    """Mais recentes primeiro."""
    consulta = com_itens().order_by(m.Pedido.criado_em.desc(), m.Pedido.id.desc())
    if marca:
        consulta = consulta.join(m.Loja, m.Loja.id == m.Pedido.loja_id).where(m.Loja.marca == marca)
    if status:
        consulta = consulta.where(m.Pedido.status == status)
    if loja_id:
        consulta = consulta.where(m.Pedido.loja_id == loja_id)
    if canal:
        consulta = consulta.where(m.Pedido.canal == canal)
    return list(db.scalars(consulta))


def do_cliente_por_numero(db: Session, cliente_id: int, numero: str) -> m.Pedido | None:
    return db.scalar(com_itens().where(m.Pedido.cliente_id == cliente_id, m.Pedido.numero == numero.strip()))


def por_numero_ou_externo(db: Session, termo: str) -> m.Pedido | None:
    """Pedido pelo número na plataforma ou pelo número no site/app de origem (pedido_externo)."""
    chave = termo.strip().upper()
    return db.scalar(
        com_itens().where((func.upper(m.Pedido.numero) == chave) | (func.upper(m.Pedido.pedido_externo) == chave)).limit(1)
    )


def reservar_numeracao(db: Session) -> list[str]:
    """Trava a numeração até o fim da transação (dois checkouts simultâneos não pegam o mesmo número)
    e devolve os números já usados."""
    db.execute(select(func.pg_advisory_xact_lock(_TRAVA_NUMERACAO)))
    # Só a numeração da Casa Lorenzi (CL-...): os pedidos migrados da Vulto têm a própria (VLT-...)
    return list(db.scalars(select(m.Pedido.numero).where(m.Pedido.numero.like("CL-%"))))


# Chave do advisory lock da numeração de pedidos (qualquer inteiro fixo e exclusivo)
_TRAVA_NUMERACAO = 104820
