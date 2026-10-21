"""Vulto+ (programa de pontos da Vulto, incorporado à plataforma).

O saldo nunca é editado direto: cada mudança é um movimento (movimentos_pontos) com quantidade com
sinal (positiva entra, negativa sai) e o saldo resultante, que nunca fica negativo. O saldo atual do
cliente é o saldo_resultante do último movimento dele.

Regras (sistema e planilhas da Vulto, com as decisões do time no registro de decisões da Vulto):
- 100 pontos = R$ 5,00 desde mar/2025 (config.valor_ponto = 0.05);
- os pontos vencem 12 meses depois de ganhos e o resgate gasta primeiro os mais antigos (decisão 22);
- a categoria vem do saldo válido (decisão 21): 0 sem categoria, 1 a 1.500 Bronze,
  1.501 a 5.000 Prata, 5.001 a 9.999 Ouro e 10.000 ou mais Vip.
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
