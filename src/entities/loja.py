"""Tipo do local de estoque: LOJA (atende o público) ou CD (centro de distribuição: só guarda e
expede, ex.: CD Cajamar da Vulto).

O site e o app da Vulto não são lojas: são canais do pedido (src/entities/pedido.py). No sistema
antigo eles eram as "lojas" 5 e 6, com um estoque que só espelhava o do CD; aqui o pedido online
fica com o local que expede (o CD, ou a Pinheiros no ship from store)."""

LOJA = "LOJA"
CD = "CD"
TIPOS_LOJA = (LOJA, CD)
TIPO_LOJA_PADRAO = LOJA
