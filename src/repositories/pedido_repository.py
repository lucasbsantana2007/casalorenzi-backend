from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from src import models as m
from src.entities.pedido import PREFIXO_NUMERO


def com_itens():
    """Pedido com os itens, a peça e o produto de cada um numa consulta só (listas com centenas de pedidos)."""
    return select(m.Pedido).options(selectinload(m.Pedido.itens).joinedload(m.ItemPedido.variacao).joinedload(m.Variacao.produto))


def obter(db: Session, pedido_id: int, travar: bool = False) -> m.Pedido | None:
    """travar=True bloqueia o pedido até o fim da transação (ex.: duas devoluções simultâneas do mesmo item)."""
    if travar:
        return db.get(m.Pedido, pedido_id, with_for_update={"of": m.Pedido})
    return db.get(m.Pedido, pedido_id)


def do_cliente(db: Session, cliente_id: int) -> list[m.Pedido]:
    return list(db.scalars(com_itens().where(m.Pedido.cliente_id == cliente_id).order_by(m.Pedido.criado_em.desc(), m.Pedido.id)))


def todos(db: Session) -> list[m.Pedido]:
    return list(db.scalars(com_itens()))


def no_periodo(db: Session, desde, ate, lojas: list[int] | None = None) -> list[m.Pedido]:
    """Pedidos criados em [desde, ate), só das lojas pedidas (o financeiro não carrega a base inteira)."""
    consulta = com_itens().where(m.Pedido.criado_em >= desde, m.Pedido.criado_em < ate)
    if lojas:
        consulta = consulta.where(m.Pedido.loja_id.in_(lojas))
    return list(db.scalars(consulta).unique())


def por_ids(db: Session, ids: set[int]) -> list[m.Pedido]:
    return list(db.scalars(com_itens().where(m.Pedido.id.in_(ids))).unique()) if ids else []


def contar_do_cliente(db: Session, cliente_id: int) -> int:
    return db.scalar(select(func.count()).where(m.Pedido.cliente_id == cliente_id))


def listar(
    db: Session,
    *,
    status: str | None = None,
    loja_id: int | None = None,
    canal: str | None = None,
    marca: str | None = None,
    busca: str | None = None,
    limite: int | None = None,
) -> list[m.Pedido]:
    """Mais recentes primeiro. marca: só os das lojas dessa marca. busca: número do pedido, nome ou e-mail
    do cliente ou o contato digitado na venda sem cadastro (no banco inteiro, antes do limite)."""
    # A lista do painel marca "Aguardando transferência": as transferências vêm numa consulta só
    consulta = com_itens().options(selectinload(m.Pedido.transferencias)).order_by(m.Pedido.criado_em.desc(), m.Pedido.id.desc())
    if marca:
        consulta = consulta.where(m.Pedido.loja_id.in_(select(m.Loja.id).where(m.Loja.marca == marca)))
    if busca and busca.strip():
        termo = f"%{busca.strip()}%"
        clientes = select(m.Cliente.id).where(or_(m.Cliente.nome.ilike(termo), m.Cliente.email.ilike(termo)))
        consulta = consulta.where(
            or_(m.Pedido.numero.ilike(termo), m.Pedido.cliente_contato.ilike(termo), m.Pedido.cliente_id.in_(clientes))
        )
    if status:
        consulta = consulta.where(m.Pedido.status == status)
    if loja_id:
        consulta = consulta.where(m.Pedido.loja_id == loja_id)
    if canal:
        consulta = consulta.where(m.Pedido.canal == canal)
    if limite:
        consulta = consulta.limit(limite)
    return list(db.scalars(consulta).unique())


def do_cliente_por_numero(db: Session, cliente_id: int, numero: str) -> m.Pedido | None:
    return db.scalar(com_itens().where(m.Pedido.cliente_id == cliente_id, m.Pedido.numero == numero.strip()))


def reservar_numeracao(db: Session) -> list[str]:
    """Trava a numeração até o fim da transação (dois checkouts simultâneos não pegam o mesmo número)
    e devolve os números já usados na sequência CL- (os pedidos da Vulto têm outra numeração)."""
    db.execute(select(func.pg_advisory_xact_lock(_TRAVA_NUMERACAO)))
    return list(db.scalars(select(m.Pedido.numero).where(m.Pedido.numero.startswith(PREFIXO_NUMERO, autoescape=True))))


# Chave do advisory lock da numeração de pedidos (qualquer inteiro fixo e exclusivo)
_TRAVA_NUMERACAO = 104820
