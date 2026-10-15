"""Produto na vitrine: a coleção (gênero) define em qual página ele aparece (Masculino ou
Feminino) e a estação filtra dentro dela. Peça atemporal aparece em qualquer estação.
Espelha os filtros de src/pages/ColecaoPage.jsx do frontend."""

import re

GENEROS = ("Masculino", "Feminino")
ESTACOES = ("Inverno", "Verão", "Atemporal")
ESTACAO_PADRAO = "Atemporal"


def alias_normalizado(grafia: str) -> str:
    """Forma de busca de uma grafia de SKU (sku_alias): maiúscula, sem espaços nas pontas, espaços únicos."""
    return re.sub(r"\s+", " ", str(grafia).strip()).upper()
