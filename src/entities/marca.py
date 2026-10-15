"""Marca: a plataforma atende a Casa Lorenzi e a Vulto (rede comprada em 2026).

A marca é uma dimensão das lojas e dos produtos, não uma tabela separada. Pedidos, estoques,
movimentações e atendimentos herdam a marca pela loja ou pelo produto. Cliente não tem marca:
a mesma pessoa pode comprar nas duas redes e é um registro só.

Uma variação só tem estoque em lojas da mesma marca do produto (criação de loja, transferências
e expedição respeitam isso)."""

LORENZI = "LORENZI"
VULTO = "VULTO"
MARCAS = (LORENZI, VULTO)
MARCA_PADRAO = LORENZI

# O site (vitrine, página Lojas, checkout e expedição) é o da Casa Lorenzi
MARCA_DO_SITE = LORENZI


def marca_visivel(marca_pedida: str | None, equipe: bool) -> str | None:
    """Marca a mostrar nas consultas públicas: a equipe escolhe (None = todas); visitante e cliente
    veem só a marca do site."""
    return marca_pedida if equipe else MARCA_DO_SITE
