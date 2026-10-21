"""Marca: a plataforma atende a Casa Lorenzi e a Vulto (rede comprada em 2026).

A marca é uma dimensão das lojas, dos produtos e dos atendimentos, e não uma tabela separada:
pedidos, estoques e movimentações herdam a marca pela loja ou pelo produto. Cliente não tem marca:
a mesma pessoa pode comprar nas duas redes e é um registro só (a chave é o CPF).

O que já existia antes da união é da Casa Lorenzi (MARCA_PADRAO)."""

LORENZI = "LORENZI"
VULTO = "VULTO"
MARCAS = (LORENZI, VULTO)
MARCA_PADRAO = LORENZI
