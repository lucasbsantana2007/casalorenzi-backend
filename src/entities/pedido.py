"""Pedido de venda (loja física ou e-commerce)."""

STATUS_PEDIDO = ("PROCESSANDO", "ENVIADO", "ENTREGUE", "CANCELADO")
CANAIS = ("Loja física", "E-commerce")
# Frete e endereço de entrega só existem no e-commerce (ficam nulos na loja física)
TIPOS_FRETE = ("PADRAO", "EXPRESSO")
