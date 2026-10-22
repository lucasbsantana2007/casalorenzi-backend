"""Marca: a plataforma atende a Casa Lorenzi e a Vulto (rede comprada em 2026).

A marca é uma dimensão das lojas, dos produtos e dos atendimentos, e não uma tabela separada:
pedidos, estoques e movimentações herdam a marca pela loja ou pelo produto. Cliente não tem marca:
a mesma pessoa pode comprar nas duas redes e é um registro só (a chave é o CPF).

O que já existia antes da união é da Casa Lorenzi (MARCA_PADRAO)."""

LORENZI = "LORENZI"
VULTO = "VULTO"
MARCAS = (LORENZI, VULTO)
MARCA_PADRAO = LORENZI

# O site é um só para as duas marcas, cada uma com a sua vitrine (/ = Casa Lorenzi, /vulto = Vulto):
# a vitrine e a página Lojas pedem a marca (?marca=); sem ela, o visitante recebe a do início do site.
# Sacola, login, checkout e Vulto+ são compartilhados; a peça sai de uma loja da marca dela.
MARCA_DO_SITE = LORENZI
