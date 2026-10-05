"""Funções auxiliares compartilhadas pelas rotas."""

import unicodedata
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException

from app.config import FUSO


def agora() -> datetime:
    return datetime.now(timezone.utc)


def ms(valor: datetime | None) -> int | None:
    """O frontend trabalha com datas em milissegundos (como Date.now())."""
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return int(valor.timestamp() * 1000)


def de_ms(valor: int) -> datetime:
    return datetime.fromtimestamp(valor / 1000, tz=timezone.utc)


def ler_data(valor: str | None, campo: str = "data") -> date | None:
    """Converte 'yyyy-mm-dd' em date, com mensagem de erro amigável."""
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise HTTPException(422, f"Data inválida em '{campo}'. Use o formato aaaa-mm-dd.") from None


def inicio_do_dia(dia: date) -> datetime:
    return datetime.combine(dia, time.min, tzinfo=FUSO)


def fim_do_dia(dia: date) -> datetime:
    """Primeiro instante do dia seguinte (use com '<')."""
    return inicio_do_dia(dia + timedelta(days=1))


def normalizar(texto: str | None) -> str:
    sem_acento = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn").lower()


def corresponde(busca: str | None, *campos) -> bool:
    """Busca sem diferenciar acentos e maiúsculas, como a camada de mocks do frontend."""
    if not busca or not busca.strip():
        return True
    termo = normalizar(busca.strip())
    return any(termo in normalizar(str(campo or "")) for campo in campos)


def chave_texto(texto: str | None) -> tuple[str, str]:
    """Ordenação alfabética como o localeCompare do navegador (ignora acentos e maiúsculas)."""
    return normalizar(texto), texto or ""


def lista_csv(valor: str | None) -> list[str]:
    return [item for item in (valor or "").split(",") if item]


def status_estoque(quantidade: int, quantidade_min: int) -> str:
    if quantidade <= 0:
        return "SEM_ESTOQUE"
    if quantidade <= quantidade_min:
        return "BAIXO"
    return "NORMAL"
