"""Vulto+ (programa de pontos da Vulto, incorporado à plataforma).

O saldo nunca é editado direto: cada mudança é um movimento (movimentos_pontos) com quantidade com
sinal (positiva entra, negativa sai) e o saldo resultante, que nunca fica negativo. O saldo atual do
cliente é o saldo_resultante do último movimento dele.

Regras (sistema e planilhas da Vulto, com as decisões do time no registro de decisões da Vulto):
- 100 pontos = R$ 5,00 desde mar/2025 (config.valor_ponto = 0.05);
- os pontos vencem 12 meses depois de ganhos, em todas as categorias, e o resgate gasta primeiro os mais
  antigos (decisões 22 e 69);
- a categoria vem do saldo válido (decisão 21): 0 sem categoria, 1 a 1.500 Bronze,
  1.501 a 5.000 Prata, 5.001 a 9.999 Ouro e 10.000 ou mais Vip.

Ganho (aba LEIA ISSO da Vulto, com as decisões 67 e 68 da união):
- R$ 1 em produtos = 1 ponto na loja física e 2 no site e no app (o frete não conta);
- bônus pela categoria do cliente na hora da compra: Ouro +25% e Vip +50%;
- só depois do pagamento aprovado; compra cancelada perde os pontos dela (estorno);
- compras da Casa Lorenzi também ganham pontos Vulto+.

Resgate no checkout: 100 pontos = R$ 5,00, a partir de 100 pontos e só em múltiplos de 100, sem
passar do saldo nem do valor dos produtos, e só em compras com pelo menos R$ 500 em produtos, sem o
frete (decisão 6 da Vulto).
"""

from decimal import Decimal

TIPOS_MOVIMENTO_PONTOS = ("SALDO_INICIAL", "CREDITO", "RESGATE", "ESTORNO", "AJUSTE", "VENCIMENTO")

# Sinal da quantidade de cada tipo: 1 só entra, -1 só sai, 0 aceita os dois
SINAL_POR_TIPO = {
    "SALDO_INICIAL": 1,  # saldo da planilha congelado em 01/01/2025 (decisão 19 da Vulto)
    "CREDITO": 1,  # pontos de uma compra
    "RESGATE": -1,  # pontos trocados por desconto
    "ESTORNO": -1,  # pontos de uma compra cancelada
    "AJUSTE": 0,  # correção manual (cortesia, bônus, resgate maior que o saldo...)
    "VENCIMENTO": -1,  # pontos com mais de 12 meses
}

VALOR_PONTO = Decimal("0.05")
VALIDADE_MESES = 12

# Pontos por real em produtos, pelo canal da venda
PONTOS_POR_REAL = {"Loja física": 1, "E-commerce": 2, "App": 2}
# Bônus pela categoria na hora da compra (decisão 68: Ouro +25% e Vip +50%)
BONUS_CATEGORIA = {"OURO": Decimal("0.25"), "VIP": Decimal("0.50")}

RESGATE_MULTIPLO = 100
COMPRA_MINIMA_RESGATE = Decimal("500.00")

CATEGORIAS_FIDELIDADE = ("BRONZE", "PRATA", "OURO", "VIP")
# (saldo mínimo, categoria), do maior para o menor
FAIXAS_CATEGORIA = ((10000, "VIP"), (5001, "OURO"), (1501, "PRATA"), (1, "BRONZE"))


def restricao_sinal() -> str:
    """Condição SQL que obriga cada tipo a respeitar o próprio sinal (e nenhuma quantidade zero)."""
    entram = ", ".join(f"'{t}'" for t, s in SINAL_POR_TIPO.items() if s == 1)
    saem = ", ".join(f"'{t}'" for t, s in SINAL_POR_TIPO.items() if s == -1)
    return f"quantidade <> 0 AND (tipo NOT IN ({entram}) OR quantidade > 0) AND (tipo NOT IN ({saem}) OR quantidade < 0)"


def categoria_pelo_saldo(saldo: int) -> str | None:
    """Sem pontos, sem categoria."""
    return next((nome for minimo, nome in FAIXAS_CATEGORIA if saldo >= minimo), None)


def valor_em_reais(pontos: int) -> Decimal:
    return (pontos * VALOR_PONTO).quantize(Decimal("0.01"))


def pontos_da_compra(valor_produtos: Decimal, canal: str, categoria: str | None) -> int:
    """Pontos que uma compra gera: produtos × pontos por real do canal × (1 + bônus da categoria),
    arredondado para o inteiro mais próximo (meio ponto sobe)."""
    base = Decimal(valor_produtos) * PONTOS_POR_REAL.get(canal, 1)
    total = base * (1 + BONUS_CATEGORIA.get(categoria or "", Decimal("0")))
    return max(int(total.quantize(Decimal("1"), rounding="ROUND_HALF_UP")), 0)


def desconto_do_resgate(pontos: int) -> Decimal:
    return valor_em_reais(pontos)


def maximo_resgatavel(saldo: int, valor_produtos: Decimal) -> int:
    """Mais pontos que dá para usar numa compra: o saldo, sem passar do valor dos produtos, em múltiplos de 100."""
    cabe_nos_produtos = int(Decimal(valor_produtos) / VALOR_PONTO)
    return min(saldo, cabe_nos_produtos) // RESGATE_MULTIPLO * RESGATE_MULTIPLO


def pode_resgatar(valor_produtos: Decimal) -> bool:
    return Decimal(valor_produtos) >= COMPRA_MINIMA_RESGATE
