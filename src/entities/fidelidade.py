"""Vulto+ (programa de pontos da Vulto). Conta de pontos por cliente (pontos só com CPF) e o
extrato em movimentos com quantidade com sinal: positiva entra, negativa sai. O saldo da conta é
a soma dos movimentos e nunca fica negativo.

As regras de pontuação, validade e valor do ponto chegam com a migração da fidelidade."""

CATEGORIAS_FIDELIDADE = ("BRONZE", "PRATA", "OURO")

TIPOS_MOVIMENTO_PONTOS = ("SALDO_INICIAL", "CREDITO", "RESGATE", "ESTORNO", "AJUSTE", "VENCIMENTO")

# Sinal da quantidade de cada tipo: 1 só entra, -1 só sai, 0 aceita os dois
SINAL_POR_TIPO = {
    "SALDO_INICIAL": 1,
    "CREDITO": 1,
    "RESGATE": -1,
    "ESTORNO": -1,
    "AJUSTE": 0,
    "VENCIMENTO": -1,
}

# pontos_mov.tipo do legado: C crédito, D resgate, E estorno (já vem negativo), AJ ajuste manual
TIPO_POR_CODIGO_LEGADO = {"C": "CREDITO", "D": "RESGATE", "E": "ESTORNO", "AJ": "AJUSTE"}


def restricao_sinal() -> str:
    """Condição SQL que obriga cada tipo a respeitar o próprio sinal (e nenhuma quantidade zero)."""
    entram = ", ".join(f"'{t}'" for t, s in SINAL_POR_TIPO.items() if s == 1)
    saem = ", ".join(f"'{t}'" for t, s in SINAL_POR_TIPO.items() if s == -1)
    return f"quantidade <> 0 AND (tipo NOT IN ({entram}) OR quantidade > 0) AND (tipo NOT IN ({saem}) OR quantidade < 0)"
