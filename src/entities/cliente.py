"""Cliente da loja: sem login. Identificado pelo e-mail (único, sempre em minúsculas) e
liberado em "Meus pedidos" por um PIN de 4 dígitos, guardado só como hash (bcrypt).

Erros seguidos de PIN bloqueiam a consulta por um tempo; "esqueci o PIN" gera um link
(token) de uso único com validade curta."""

import re
from datetime import datetime, timedelta

TENTATIVAS_PIN_MAX = 5
BLOQUEIO_PIN = timedelta(minutes=15)
VALIDADE_TOKEN_PIN = timedelta(minutes=30)

_PIN = re.compile(r"^\d{4}$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalizar_email(email: str | None) -> str:
    return (email or "").strip().lower()


def email_valido(email: str | None) -> bool:
    return bool(_EMAIL.match(normalizar_email(email)))


def pin_valido(pin: str | None) -> bool:
    return bool(_PIN.match(pin or ""))


def bloqueado(bloqueado_ate: datetime | None, agora: datetime) -> bool:
    return bloqueado_ate is not None and bloqueado_ate > agora


def apos_erro_de_pin(tentativas: int, agora: datetime) -> tuple[int, datetime | None]:
    """(tentativas, bloqueado_ate) depois de um PIN errado: na 5ª seguida, bloqueia e zera o contador."""
    tentativas += 1
    if tentativas >= TENTATIVAS_PIN_MAX:
        return 0, agora + BLOQUEIO_PIN
    return tentativas, None
