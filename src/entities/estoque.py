"""Estoque = loja + variação (SKU). O saldo nunca é editado direto: toda mudança é uma
movimentação com quantidade com sinal (positiva entra, negativa sai)."""

TIPOS_MOVIMENTACAO = ("ENTRADA", "VENDA", "DEVOLUCAO", "AJUSTE", "TRANSFERENCIA_SAIDA", "TRANSFERENCIA_ENTRADA")

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
