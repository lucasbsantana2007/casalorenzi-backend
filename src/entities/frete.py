"""Frete do e-commerce por região do CEP. Espelha src/utils/frete.js do frontend: a loja mostra
as opções antes da compra e a API recalcula no checkout (o valor nunca vem do navegador)."""

import re
from decimal import Decimal

# Pedidos a partir deste valor têm o frete padrão grátis
FRETE_GRATIS_MINIMO = Decimal("1000")

# Faixas de CEP (8 dígitos, como número) por região: (início, fim, região)
_FAIXAS = (
    (1000000, 19999999, "SP"),
    (20000000, 28999999, "SUDESTE"),  # RJ
    (29000000, 39999999, "SUDESTE"),  # ES e MG
    (80000000, 99999999, "SUL"),
    (70000000, 79999999, "CENTRO_OESTE"),
    (40000000, 65999999, "NORDESTE"),
    (66000000, 69999999, "NORTE"),
)

# região → {tipo: (valor, prazo em dias úteis)}
_TABELA = {
    "SP": {"PADRAO": ("19.90", 3), "EXPRESSO": ("39.90", 1)},
    "SUDESTE": {"PADRAO": ("29.90", 5), "EXPRESSO": ("59.90", 2)},
    "SUL": {"PADRAO": ("34.90", 6), "EXPRESSO": ("64.90", 3)},
    "CENTRO_OESTE": {"PADRAO": ("39.90", 7), "EXPRESSO": ("74.90", 3)},
    "NORDESTE": {"PADRAO": ("44.90", 9), "EXPRESSO": ("84.90", 4)},
    "NORTE": {"PADRAO": ("54.90", 12), "EXPRESSO": ("99.90", 5)},
}

ROTULOS = {"PADRAO": "Padrão", "EXPRESSO": "Expresso"}


def somente_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def regiao_do_cep(cep: str | None) -> str | None:
    digitos = somente_digitos(cep)
    if len(digitos) != 8:
        return None
    numero = int(digitos)
    return next((regiao for inicio, fim, regiao in _FAIXAS if inicio <= numero <= fim), None)


def opcao_de_frete(cep: str | None, subtotal: Decimal, tipo: str) -> tuple[Decimal, int] | None:
    """(valor, prazo em dias) do frete escolhido, ou None se o CEP não é atendido ou o tipo não existe."""
    regiao = regiao_do_cep(cep)
    if regiao is None or tipo not in _TABELA[regiao]:
        return None
    valor, prazo = _TABELA[regiao][tipo]
    if tipo == "PADRAO" and subtotal >= FRETE_GRATIS_MINIMO:
        return Decimal("0"), prazo
    return Decimal(valor), prazo


def uf_do_cep(cep: str | None) -> str | None:
    """UF aproximada pelo CEP, usada só para preferir a loja mais próxima na expedição."""
    prefixo = somente_digitos(cep)[:2]
    if not prefixo:
        return None
    numero = int(prefixo)
    if 1 <= numero <= 19:
        return "SP"
    if 20 <= numero <= 28:
        return "RJ"
    if 80 <= numero <= 87:
        return "PR"
    return None
