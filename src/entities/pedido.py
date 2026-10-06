"""Pedido de venda (loja física ou e-commerce)."""

STATUS_PEDIDO = ("PROCESSANDO", "ENVIADO", "ENTREGUE", "CANCELADO")
CANAIS = ("Loja física", "E-commerce")
# Frete e endereço de entrega só existem no e-commerce (ficam nulos na loja física)
TIPOS_FRETE = ("PADRAO", "EXPRESSO")

PREFIXO_NUMERO = "CL-"
# Número dos pedidos do e-commerce: segue a sequência dos existentes (CL-104820, CL-104827, ...)
NUMERO_INICIAL = 104820
PASSO_NUMERO = 7

# Mudanças de status feitas pela equipe no painel
#   PROCESSANDO → ENVIADO (com código de rastreio; baixa as peças da loja de expedição)
#   ENVIADO → ENTREGUE
#   PROCESSANDO → CANCELADO (estorna o pagamento e cancela as transferências pendentes)
TRANSICOES = {("PROCESSANDO", "ENVIADO"), ("ENVIADO", "ENTREGUE"), ("PROCESSANDO", "CANCELADO")}


def pode_mudar(de: str, para: str) -> bool:
    return (de, para) in TRANSICOES


def proximo_numero(numeros: list[str]) -> str:
    """Próximo número da sequência a partir dos números já usados."""
    maior = max((int(n) for n in (_digitos(numero) for numero in numeros) if n), default=NUMERO_INICIAL)
    return f"{PREFIXO_NUMERO}{max(maior, NUMERO_INICIAL) + PASSO_NUMERO}"


def _digitos(numero: str) -> str:
    return "".join(c for c in numero if c.isdigit())


def pontuar_loja(itens_cobertos: int, mesma_uf: bool) -> int:
    """Loja de expedição: a que tem mais itens da sacola em estoque; empate → mesma UF do CEP."""
    return itens_cobertos * 10 + (1 if mesma_uf else 0)
