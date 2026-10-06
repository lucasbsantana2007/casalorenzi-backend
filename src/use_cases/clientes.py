"""Clientes vistos pela equipe no painel. Cliente não tem login: não existe portal com conta;
a consulta pública de pedidos é por e-mail + PIN ("Meus pedidos")."""

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
