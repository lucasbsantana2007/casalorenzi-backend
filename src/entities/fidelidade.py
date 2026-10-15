"""Vulto+ (programa de pontos da Vulto, incorporado à plataforma). O saldo nunca é editado direto: cada
mudança é um movimento com quantidade com sinal (positiva entra, negativa sai) e o saldo resultante,
que nunca fica negativo (aba LEIA ISSO da planilha de clientes da Vulto: "NÃO pode ficar negativo").

Resgate no checkout: 100 pontos = R$ 5,00 (regra da Vulto desde mar/2025), a partir de 100 pontos e só
em múltiplos de 100, e só em compras com pelo menos R$ 500 em produtos, sem o frete (decisão do time em
15/10/2026: libera o resgate em cerca de 25% das compras da Vulto). O desconto não passa do valor dos
produtos."""

from decimal import Decimal

TIPOS_MOVIMENTO_PONTOS = ("SALDO_INICIAL", "CREDITO", "RESGATE", "ESTORNO", "AJUSTE")

VALOR_PONTO = Decimal("0.05")
RESGATE_MULTIPLO = 100
COMPRA_MINIMA_RESGATE = Decimal("500.00")


def desconto_do_resgate(pontos: int) -> Decimal:
    return (pontos * VALOR_PONTO).quantize(Decimal("0.01"))


def maximo_resgatavel(saldo: int, subtotal: Decimal) -> int:
    """Mais pontos que dá para usar numa compra: o saldo, sem passar do valor dos produtos, em múltiplos de 100."""
    cabe_no_subtotal = int(Decimal(subtotal) / VALOR_PONTO)
    return min(saldo, cabe_no_subtotal) // RESGATE_MULTIPLO * RESGATE_MULTIPLO
