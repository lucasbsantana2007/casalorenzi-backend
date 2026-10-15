"""Cliente da loja: conta própria com CPF, e-mail (único, sempre em minúsculas) e senha (só o hash).

A conta nasce no checkout ou em "Criar conta" e entra pelo mesmo login da equipe. "Esqueci a
senha" gera um link (token) de uso único com validade curta."""

import re
from datetime import timedelta

VALIDADE_TOKEN_SENHA = timedelta(minutes=30)
SENHA_MINIMA = 8

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalizar_email(email: str | None) -> str:
    return (email or "").strip().lower()


def email_valido(email: str | None) -> bool:
    return bool(_EMAIL.match(normalizar_email(email)))


def somente_digitos_cpf(cpf: str | None) -> str:
    return re.sub(r"\D", "", cpf or "")[:11]


def cpf_do_id(valor: str | int | None) -> str:
    """O id público do cliente é o CPF (11 dígitos). Aceita com máscara ou como número (zeros à esquerda)."""
    if isinstance(valor, int):
        return str(valor).zfill(11)
    return somente_digitos_cpf(str(valor or ""))


def _digito_verificador(base: str) -> int:
    soma = sum(int(d) * (len(base) + 1 - i) for i, d in enumerate(base))
    resto = (soma * 10) % 11
    return 0 if resto == 10 else resto


def cpf_valido(cpf: str | None) -> bool:
    """11 dígitos, não todos iguais, e os dois dígitos verificadores corretos."""
    d = somente_digitos_cpf(cpf)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    return _digito_verificador(d[:9]) == int(d[9]) and _digito_verificador(d[:10]) == int(d[10])


def telefone_e164(valor: str | int | None) -> str | None:
    """Telefone brasileiro em E.164 (+5511948854328), ou None se não der para saber o número completo:
    aceita "11951021527", "+55 11 91217-2644", "(11) 98369-1660"; sem DDD ("90429-6274"), None."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11) or digitos[0] == "0" or digitos[1] == "0":
        return None
    celular = len(digitos) == 11 and digitos[2] == "9"
    fixo = len(digitos) == 10 and digitos[2] in "2345"
    return f"+55{digitos}" if celular or fixo else None
