"""Vulto+: saldo e extrato do cliente, resgate de pontos no checkout e devolução no cancelamento.
Regras em src/entities/fidelidade.py.

- Resgate: a partir de 100 pontos, em múltiplos de 100, só com pelo menos R$ 500 em produtos (sem o
  frete) e sem passar do saldo nem do valor dos produtos. O cliente fica travado até o fim da compra.
- Pedido cancelado devolve os pontos usados nele (ajuste positivo no extrato, ligado ao pedido).
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from src import models as m
from src.entities import fidelidade as regra
from src.repositories import fidelidade_repository, sessao
from src.utils.erros import DadosInvalidos


def _brl(valor: Decimal) -> str:
    return f"R$ {valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def lancar(
    db: Session, cliente_id: int, tipo: str, quantidade: int, quando: datetime, *, pedido=None, obs=""
) -> m.MovimentoPontos:
    """Grava o movimento com o novo saldo. Quem chama já travou o cliente (travar_cliente)."""
    novo_saldo = fidelidade_repository.saldo(db, cliente_id) + quantidade
    if novo_saldo < 0:
        raise DadosInvalidos("O saldo de pontos não pode ficar negativo.")
    movimento = m.MovimentoPontos(
        cliente_id=cliente_id,
        tipo=tipo,
        quantidade=quantidade,
        saldo_resultante=novo_saldo,
        pedido=pedido,
        obs=obs,
        criado_em=quando,
    )
    sessao.adicionar(db, movimento)
    sessao.gerar_ids(db)  # o próximo lançamento na mesma transação já enxerga este saldo
    return movimento


def extrato(db: Session, cliente: m.Cliente) -> tuple[int, list[m.MovimentoPontos]]:
    return fidelidade_repository.saldo(db, cliente.id), fidelidade_repository.extrato(db, cliente.id)


def conferir_resgate(db: Session, cliente: m.Cliente, subtotal: Decimal, pontos: int) -> Decimal:
    """Desconto do resgate pedido no checkout (zero sem pontos). Trava o cliente até o fim da compra."""
    if not pontos:
        return Decimal("0")
    if pontos < 0 or pontos % regra.RESGATE_MULTIPLO:
        raise DadosInvalidos(f"Use os pontos Vulto+ em múltiplos de {regra.RESGATE_MULTIPLO}.")
    if subtotal < regra.COMPRA_MINIMA_RESGATE:
        minimo = _brl(regra.COMPRA_MINIMA_RESGATE)
        raise DadosInvalidos(f"Para usar pontos Vulto+, a compra precisa ter pelo menos {minimo} em produtos (sem o frete).")
    fidelidade_repository.travar_cliente(db, cliente.id)
    saldo = fidelidade_repository.saldo(db, cliente.id)
    if pontos > saldo:
        raise DadosInvalidos(f"Saldo Vulto+ insuficiente: você tem {saldo} pontos.")
    maximo = regra.maximo_resgatavel(saldo, subtotal)
    if pontos > maximo:
        raise DadosInvalidos(f"Nesta compra dá para usar no máximo {maximo} pontos (o desconto não passa do valor dos produtos).")
    return regra.desconto_do_resgate(pontos)


def registrar_resgate(db: Session, cliente: m.Cliente, pedido: m.Pedido, pontos: int, quando: datetime) -> None:
    lancar(
        db,
        cliente.id,
        "RESGATE",
        -pontos,
        quando,
        pedido=pedido,
        obs=f"Desconto de {_brl(regra.desconto_do_resgate(pontos))} no pedido {pedido.numero}",
    )


def devolver_resgate(db: Session, pedido: m.Pedido, quando: datetime) -> int:
    """Pedido cancelado: os pontos usados nele voltam. Devolve quantos voltaram."""
    pontos = fidelidade_repository.resgatado_no_pedido(db, pedido.id)
    if not pontos:
        return 0
    fidelidade_repository.travar_cliente(db, pedido.cliente_id)
    lancar(
        db,
        pedido.cliente_id,
        "AJUSTE",
        pontos,
        quando,
        pedido=pedido,
        obs=f"Pedido {pedido.numero} cancelado: pontos do resgate devolvidos",
    )
    return pontos
