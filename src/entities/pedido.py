"""Pedido de venda (loja física, e-commerce ou app).

total = subtotal (soma dos itens) − desconto + frete. O banco confere essa conta em cada pedido.
"""

STATUS_PEDIDO = ("PROCESSANDO", "ENVIADO", "ENTREGUE", "CANCELADO")

# O canal é guardado pelo rótulo, porque o frontend filtra por ele. "App" é o app da Vulto
# (o sistema antigo chamava o e-commerce de "Site").
CANAL_LOJA = "Loja física"
CANAL_ECOMMERCE = "E-commerce"
CANAL_APP = "App"
CANAIS = (CANAL_LOJA, CANAL_ECOMMERCE, CANAL_APP)
CANAIS_ONLINE = (CANAL_ECOMMERCE, CANAL_APP)

# VENDA: venda normal. TROCA: a Vulto lançava a troca como uma venda nova pelo preço cheio, só para
# baixar a peça nova do estoque. A troca movimenta o estoque, mas não é receita (a venda original já
# contou): registro de decisões da Vulto, decisão 16.
TIPOS_PEDIDO = ("VENDA", "TROCA")
TIPO_PEDIDO_PADRAO = "VENDA"
TIPOS_SEM_RECEITA = ("TROCA",)

# Frete e endereço de entrega só existem nas vendas online (ficam nulos na loja física)
TIPOS_FRETE = ("PADRAO", "EXPRESSO")

PREFIXO_NUMERO = "CL-"
# Número dos pedidos do e-commerce: segue a sequência dos existentes (CL-104820, CL-104827, ...).
# Pedidos de outra numeração (os da Vulto: S100234, APP-7001205...) ficam fora da conta.
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
    """Próximo número da sequência CL- a partir dos números já usados (os de outro prefixo não contam)."""
    da_sequencia = (_digitos(numero) for numero in numeros if numero.startswith(PREFIXO_NUMERO))
    maior = max((int(n) for n in da_sequencia if n), default=NUMERO_INICIAL)
    return f"{PREFIXO_NUMERO}{max(maior, NUMERO_INICIAL) + PASSO_NUMERO}"


def _digitos(numero: str) -> str:
    return "".join(c for c in numero if c.isdigit())


def pontuar_loja(itens_cobertos: int, mesma_uf: bool) -> int:
    """Loja de expedição: a que tem mais itens da sacola em estoque; empate → mesma UF do CEP."""
    return itens_cobertos * 10 + (1 if mesma_uf else 0)
