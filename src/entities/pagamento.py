"""Pagamento de um pedido. Um pedido pode ter mais de um pagamento (ex.: parte no PIX, parte
no cartão); o pedido está pago quando a soma dos APROVADOS cobre o total.

PENDENTE → APROVADO → ESTORNADO
PENDENTE → ESTORNADO (pagamento que não se concretizou)
"""

from decimal import Decimal

METODOS_PAGAMENTO = ("PIX", "CARTAO", "DINHEIRO", "DEBITO")
METODOS_ECOMMERCE = ("PIX", "CARTAO")
STATUS_PAGAMENTO = ("APROVADO", "ESTORNADO", "PENDENTE")
PARCELAS_MAX = 6

TRANSICOES = {
    ("PENDENTE", "APROVADO"),
    ("PENDENTE", "ESTORNADO"),
    ("APROVADO", "ESTORNADO"),
}

# Usado para pedidos antigos, que não registravam a forma de pagamento (migration e carga)
METODO_PADRAO_POR_CANAL = {"E-commerce": "CARTAO", "Loja física": "DEBITO"}


def pode_mudar(de: str, para: str) -> bool:
    return (de, para) in TRANSICOES


def parcelas_validas(metodo: str, parcelas: int) -> bool:
    """Só cartão de crédito parcela (até 6x); os demais métodos são sempre 1x."""
    if metodo == "CARTAO":
        return 1 <= parcelas <= PARCELAS_MAX
    return parcelas == 1


def status_inicial(status_pedido: str) -> str:
    """Pedido cancelado não fica com pagamento aprovado: o valor já foi devolvido."""
    return "ESTORNADO" if status_pedido == "CANCELADO" else "APROVADO"


def valor_aprovado(pagamentos) -> Decimal:
    return sum((p.valor for p in pagamentos if p.status == "APROVADO"), Decimal("0"))
