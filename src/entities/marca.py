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
# Sacola, login, checkout e Lupe+ são compartilhados; a peça sai de uma loja da marca dela.
MARCA_DO_SITE = LORENZI

# Marca de cada funcionário da equipe: trabalha só com a Casa Lorenzi, só com a Vulto ou, para o
# Administrador do grupo, com as duas (GRUPO). Quem não é do grupo não vê nem altera nada da outra
# marca: produtos, estoque, pedidos, transferências, atendimentos, financeiro, lojas e funcionários.
GRUPO = "GRUPO"
MARCAS_EQUIPE = (LORENZI, VULTO, GRUPO)


def marca_do_escopo(marca_do_usuario: str, pedida: str | None = None) -> str | None:
    """Marca que o funcionário enxerga: a dele; o Administrador do grupo vê as duas (None) ou a que
    escolheu no seletor do painel (pedida)."""
    if marca_do_usuario == GRUPO:
        return pedida if pedida in MARCAS else None
    return marca_do_usuario


def na_marca(escopo: str | None, marca: str | None) -> bool:
    """O dado (de uma loja, produto ou atendimento com essa marca) está no escopo do funcionário?"""
    return escopo is None or (marca or MARCA_PADRAO) == escopo
