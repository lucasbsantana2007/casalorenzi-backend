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
    # Central administrativa: funcionários, lojas, frete e log de ações
    "administracao": (ADMINISTRADOR,),
}


def pode_acessar(papel: str, modulo: str) -> bool:
    return papel in ACESSO[modulo]


def loja_do_escopo(papel: str, loja_id: int | None) -> int | None:
    """Loja a que o membro da equipe está restrito nos pedidos: Lojista e Operador veem só os pedidos
    da própria loja; o Administrador vê a rede toda (None). Sem loja cadastrada, não vê nenhum (0)."""
    if papel == ADMINISTRADOR:
        return None
    return loja_id or 0


def ve_pedido_da_loja(papel: str, loja_do_usuario: int | None, loja_do_pedido: int) -> bool:
    escopo = loja_do_escopo(papel, loja_do_usuario)
    return escopo is None or escopo == loja_do_pedido
