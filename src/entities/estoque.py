"""Estoque = loja + variação (SKU). O saldo nunca é editado direto: toda mudança é uma
movimentação com quantidade com sinal (positiva entra, negativa sai).

Tipos que vieram com o histórico da Vulto (o sistema dela só guardava o saldo atual; o histórico
foi reconstruído pelo time, decisões 44, 45 e 54 do registro da Vulto):
- SALDO_INICIAL: saldo de partida de um item (01/01/2025 na Vulto), a quantidade mínima que fecha
  com a contagem física sem deixar o estoque negativo;
- INVENTARIO: ajuste no dia da contagem física, a diferença entre o contado e o que os movimentos
  levariam a ter (a perda que o sistema não registrou);
- AVARIA: peça com defeito que sai do estoque vendável.
Movimentação com estimado=True tem quantidade estimada, não contada (ex.: avaria estimada).
"""

TIPOS_MOVIMENTACAO = (
    "ENTRADA",
    "VENDA",
    "DEVOLUCAO",
    "AJUSTE",
    "TRANSFERENCIA_SAIDA",
    "TRANSFERENCIA_ENTRADA",
    "SALDO_INICIAL",
    "INVENTARIO",
    "AVARIA",
)

# Sinal esperado nos lançamentos manuais (0 = ajuste aceita os dois)
SINAL_POR_TIPO_MANUAL = {"ENTRADA": 1, "DEVOLUCAO": 1, "VENDA": -1, "AJUSTE": 0}

# Ordem de exibição da lista de estoque: o que pede ação primeiro
ORDEM_STATUS = {"SEM_ESTOQUE": 0, "BAIXO": 1, "NORMAL": 2}


def status_estoque(quantidade: int, quantidade_min: int) -> str:
    if quantidade <= 0:
        return "SEM_ESTOQUE"
    if quantidade <= quantidade_min:
        return "BAIXO"
    return "NORMAL"


def quantidade_valida_para_tipo(tipo: str, quantidade: int) -> bool:
    sinal = SINAL_POR_TIPO_MANUAL[tipo]
    return quantidade != 0 and not (sinal and quantidade * sinal < 0)
