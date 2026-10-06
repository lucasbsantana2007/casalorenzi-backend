"""Busca e ordenação de texto como no frontend (sem diferenciar acentos e maiúsculas)."""

import unicodedata


def normalizar(texto: str | None) -> str:
    sem_acento = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn").lower()


def corresponde(busca: str | None, *campos) -> bool:
    if not busca or not busca.strip():
        return True
    termo = normalizar(busca.strip())
    return any(termo in normalizar(str(campo or "")) for campo in campos)


def chave_texto(texto: str | None) -> tuple[str, str]:
    """Ordenação alfabética como o localeCompare do navegador."""
    return normalizar(texto), texto or ""


def lista_csv(valor: str | None) -> list[str]:
    return [item for item in (valor or "").split(",") if item]


def somente_digitos(valor: str | None) -> str:
    return "".join(c for c in (valor or "") if c.isdigit())
