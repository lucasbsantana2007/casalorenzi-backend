"""Papéis da equipe e o que cada um acessa. Espelha src/utils/permissions.js do frontend:
o frontend só esconde menus; quem garante a regra é a API.

Cliente não é usuário: não tem login nem papel. Fica na tabela `clientes` e se identifica
por e-mail + PIN (src/entities/cliente.py)."""

ADMINISTRADOR = "ADMINISTRADOR"
LOJISTA = "LOJISTA"
OPERADOR = "OPERADOR"

EQUIPE = (ADMINISTRADOR, LOJISTA, OPERADOR)
PAPEIS = EQUIPE

ACESSO = {
    "dashboard": (ADMINISTRADOR, LOJISTA, OPERADOR),
    "pedidos": (ADMINISTRADOR, LOJISTA, OPERADOR),
    "estoque": (ADMINISTRADOR, LOJISTA, OPERADOR),
    "produtos": (ADMINISTRADOR,),
    "transferencias": (ADMINISTRADOR, OPERADOR),
    "atendimento": (ADMINISTRADOR, LOJISTA),
    "financeiro": (ADMINISTRADOR,),
}


def pode_acessar(papel: str, modulo: str) -> bool:
    return papel in ACESSO[modulo]
