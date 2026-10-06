"""Devolução de peças de um pedido. Cada devolução aponta para um item do pedido, devolve a
peça ao estoque da loja que a recebeu (movimentação DEVOLUCAO, quantidade positiva) e
registra o valor reembolsado (preço pago × quantidade; o frete não é reembolsado).

Regras:
- pedido CANCELADO não aceita devolução (o pagamento já foi estornado);
- pedido ainda PROCESSANDO também não: a peça nem saiu do estoque, o caminho é cancelar;
- não se devolve mais do que o comprado menos o que já foi devolvido daquele item.
"""

from decimal import Decimal

STATUS_ACEITAM_DEVOLUCAO = ("ENVIADO", "ENTREGUE")
MOTIVO_MAX = 500


def aceita_devolucao(status_pedido: str) -> bool:
    return status_pedido in STATUS_ACEITAM_DEVOLUCAO


def saldo_devolvivel(comprado: int, ja_devolvido: int) -> int:
    return max(comprado - ja_devolvido, 0)


def valor_devolvido(preco_unitario: Decimal, quantidade: int) -> Decimal:
    return (Decimal(preco_unitario) * quantidade).quantize(Decimal("0.01"))


def pedido_totalmente_devolvido(comprado_por_item: dict[int, int], devolvido_por_item: dict[int, int]) -> bool:
    """True quando todas as peças de todos os itens já voltaram."""
    return all(devolvido_por_item.get(item_id, 0) >= qtd for item_id, qtd in comprado_por_item.items())
