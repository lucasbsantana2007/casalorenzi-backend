"""Clientes: vistos pela equipe no painel e, com a própria conta, pelo cliente na área do cliente.
Quem pode ver o quê é conferido na rota (o cliente só acessa o próprio id)."""

from sqlalchemy.orm import Session

from src import models as m
from src.repositories import atendimento_repository, cliente_repository, pedido_repository
from src.utils.erros import NaoEncontrado


def listar(db: Session, busca: str | None = None) -> list[m.Cliente]:
    """Busca por nome, e-mail ou telefone (até 50 resultados)."""
    return cliente_repository.listar(db, busca)


def obter(db: Session, cliente_id: int) -> m.Cliente:
    cliente = cliente_repository.por_id(db, cliente_id)
    if cliente is None:
        raise NaoEncontrado("Cliente não encontrado.")
    return cliente


def pedidos(db: Session, cliente_id: int) -> list[m.Pedido]:
    obter(db, cliente_id)
    return pedido_repository.do_cliente(db, cliente_id)


def atendimentos(db: Session, cliente_id: int) -> list[m.Atendimento]:
    obter(db, cliente_id)
    return atendimento_repository.do_cliente(db, cliente_id)


def totais(db: Session, cliente_id: int) -> tuple[int, int]:
    """(pedidos, atendimentos) do cliente."""
    return pedido_repository.contar_do_cliente(db, cliente_id), atendimento_repository.contar_do_cliente(db, cliente_id)


def atendimento(db: Session, cliente_id: int, atendimento_id: int) -> m.Atendimento:
    """Chamado do cliente. De outro cliente: aparece como inexistente (404)."""
    a = atendimento_repository.obter(db, atendimento_id)
    if a is None or a.cliente_id != cliente_id:
        raise NaoEncontrado("Solicitação não encontrada.")
    return a


def pedido_por_numero(db: Session, cliente_id: int, numero: str) -> m.Pedido:
    """Aceita "CL-104820", "cl 104820" ou só "104820". Só pedidos do próprio cliente."""
    termo = "".join(c for c in (numero or "") if c.isdigit())
    pedido = pedido_repository.do_cliente_por_numero(db, cliente_id, f"CL-{termo}") if termo else None
    if pedido is None:
        raise NaoEncontrado("Não encontramos um pedido com esse número.")
    return pedido
