"""Papéis da equipe e o que cada um acessa. Espelha src/utils/permissions.js do frontend:
o frontend só esconde menus; quem garante a regra é a API.

Cliente não é usuário da equipe: fica na tabela `clientes`, entra pelo mesmo login com a
conta criada no checkout (e-mail + senha) e recebe um token com papel "CLIENTE"."""

ADMINISTRADOR = "ADMINISTRADOR"
LOJISTA = "LOJISTA"
OPERADOR = "OPERADOR"

EQUIPE = (ADMINISTRADOR, LOJISTA, OPERADOR)
# Papel gravado no token de um cliente logado (não é papel da equipe)
CLIENTE = "CLIENTE"
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
