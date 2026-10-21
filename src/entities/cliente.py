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


# "Dados válidos": o cadastro não tem nenhum destes problemas, que só o próprio cliente pode corrigir
# (o CPF certo, o e-mail, o DDD). Calculado do cadastro, nunca gravado: quando o cliente corrige, some sozinho.
# Na Vulto: 240 CPFs inválidos, 765 clientes sem e-mail e 319 telefones sem DDD (decisões 26, 52 e 53).
PROBLEMAS_CADASTRO = ("SEM_CPF", "CPF_INVALIDO", "SEM_EMAIL", "EMAIL_INVALIDO", "TELEFONE_SEM_DDD", "TELEFONE_INVALIDO")


def problema_do_telefone(telefone: str | None) -> str | None:
    """Telefone vazio não é problema (é opcional). Aceita +55, DDD e 8 ou 9 dígitos, com ou sem máscara."""
    d = re.sub(r"\D", "", telefone or "")
    if not d:
        return None
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) in (8, 9):
        return "TELEFONE_SEM_DDD"
    if len(d) not in (10, 11) or d.startswith("0"):
        return "TELEFONE_INVALIDO"
    return None


def problemas_do_cadastro(cpf: str | None, email: str | None, telefone: str | None) -> list[str]:
    problemas = []
    if not cpf:
        problemas.append("SEM_CPF")
    elif not cpf_valido(cpf):
        problemas.append("CPF_INVALIDO")
    if not email:
        problemas.append("SEM_EMAIL")
    elif not email_valido(email):
        problemas.append("EMAIL_INVALIDO")
    if problema := problema_do_telefone(telefone):
        problemas.append(problema)
    return problemas
