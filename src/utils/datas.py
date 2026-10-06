"""Datas: o frontend trabalha com milissegundos (como Date.now()) e filtros em aaaa-mm-dd."""

from datetime import UTC, date, datetime, time, timedelta

from src.config.settings import FUSO
from src.utils.erros import DadosInvalidos


def agora() -> datetime:
    return datetime.now(UTC)


def ms(valor: datetime | None) -> int | None:
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return int(valor.timestamp() * 1000)


def de_ms(valor: int) -> datetime:
    return datetime.fromtimestamp(valor / 1000, tz=UTC)


def ler_data(valor: str | None, campo: str = "data") -> date | None:
    """Converte 'yyyy-mm-dd' em date, com mensagem de erro amigável."""
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise DadosInvalidos(f"Data inválida em '{campo}'. Use o formato aaaa-mm-dd.") from None


def inicio_do_dia(dia: date) -> datetime:
    return datetime.combine(dia, time.min, tzinfo=FUSO)


def fim_do_dia(dia: date) -> datetime:
    """Primeiro instante do dia seguinte (use com '<')."""
    return inicio_do_dia(dia + timedelta(days=1))


def hoje() -> date:
    return agora().astimezone(FUSO).date()
