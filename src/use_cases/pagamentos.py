"""Pagamentos dos pedidos (regras em src/entities/pagamento.py).

`novo` e `estornar_aprovados` não confirmam a transação: são usados dentro de fluxos maiores
(checkout, cancelamento de pedido, devolução total), que confirmam tudo de uma vez.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src import models as m
from src.entities.pagamento import METODOS_PAGAMENTO, STATUS_PAGAMENTO, parcelas_validas, pode_mudar
from src.repositories import pagamento_repository, pedido_repository, sessao
from src.utils.datas import agora
from src.utils.erros import DadosInvalidos, NaoEncontrado


def listar_do_pedido(db: Session, pedido_id: int) -> list[m.Pagamento]:
    if pedido_repository.obter(db, pedido_id) is None:
        raise NaoEncontrado("Pedido não encontrado.")
    return pagamento_repository.do_pedido(db, pedido_id)


def novo(
    db: Session,
    pedido: m.Pedido,
    *,
    metodo: str,
    valor: Decimal,
    parcelas: int = 1,
    status: str = "APROVADO",
    quando: datetime | None = None,
) -> m.Pagamento:
    if metodo not in METODOS_PAGAMENTO:
        raise DadosInvalidos("Escolha a forma de pagamento.")
    if status not in STATUS_PAGAMENTO:
        raise DadosInvalidos("Status de pagamento inválido.")
    if not parcelas_validas(metodo, parcelas):
        raise DadosInvalidos("Número de parcelas inválido para a forma de pagamento.")
    if Decimal(valor) < 0:
        raise DadosInvalidos("Valor de pagamento inválido.")
    quando = quando or agora()
    pagamento = m.Pagamento(
        pedido=pedido, metodo=metodo, valor=valor, parcelas=parcelas, status=status, criado_em=quando, atualizado_em=quando
    )
    sessao.adicionar(db, pagamento)
    return pagamento


def estornar_aprovados(db: Session, pedido: m.Pedido, quando: datetime | None = None) -> list[m.Pagamento]:
    """APROVADO → ESTORNADO em todos os pagamentos do pedido (cancelamento ou devolução total)."""
    quando = quando or agora()
    estornados = []
    for pagamento in pagamento_repository.do_pedido(db, pedido.id):
        if pagamento.status == "APROVADO" and pode_mudar("APROVADO", "ESTORNADO"):
            pagamento.status = "ESTORNADO"
            pagamento.atualizado_em = quando
            estornados.append(pagamento)
    return estornados
