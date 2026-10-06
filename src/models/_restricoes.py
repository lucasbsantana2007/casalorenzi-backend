"""Colunas de status/tipo guardam texto; o banco só aceita os valores definidos nas entities."""


def valor_em(coluna: str, valores: tuple[str, ...]) -> str:
    lista = ", ".join(f"'{v}'" for v in valores)
    return f"{coluna} IN ({lista})"
