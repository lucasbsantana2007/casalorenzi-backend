"""Frete do e-commerce por região do CEP. Espelha src/utils/frete.js do frontend: a loja mostra
as opções antes da compra e a API recalcula no checkout (o valor nunca vem do navegador).

Valores, custos e prazos ficam no banco (config_frete e frete_regioes), editáveis pelo
Administrador; FRETE_INICIAL é a configuração de partida (seed e migração)."""

import re
from dataclasses import dataclass
from decimal import Decimal

# Faixas de CEP (8 dígitos, como número) por região: (início, fim, região)
_FAIXAS = (
    (1000000, 19999999, "SP"),
    (20000000, 28999999, "SUDESTE"),  # RJ
    (29000000, 39999999, "SUDESTE"),  # ES e MG
    (80000000, 99999999, "SUL"),
    (70000000, 79999999, "CENTRO_OESTE"),
    (40000000, 65999999, "NORDESTE"),
    (66000000, 69999999, "NORTE"),
)

TIPOS = ("PADRAO", "EXPRESSO")

# Configuração inicial: gratis_minimo, expresso_ativo e, por região,
# (regiao, nome, (valor, custo, prazo) do Padrão, (valor, custo, prazo) do Expresso).
# Os custos são de demonstração; na operação real vêm do contrato com a transportadora.
FRETE_INICIAL = {
    "gratis_minimo": Decimal("1000"),
    "expresso_ativo": True,
    "regioes": (
        ("SP", "Estado de São Paulo", ("19.90", "16.50", 3), ("39.90", "31.00", 1)),
        ("SUDESTE", "Rio de Janeiro, Espírito Santo e Minas Gerais", ("29.90", "24.00", 5), ("59.90", "46.00", 2)),
        ("SUL", "Região Sul", ("34.90", "29.00", 6), ("64.90", "52.00", 3)),
        ("CENTRO_OESTE", "Região Centro-Oeste", ("39.90", "33.00", 7), ("74.90", "58.00", 3)),
        ("NORDESTE", "Região Nordeste", ("44.90", "38.00", 9), ("84.90", "66.00", 4)),
        ("NORTE", "Região Norte", ("54.90", "47.00", 12), ("99.90", "78.00", 5)),
    ),
}


@dataclass(frozen=True)
class OpcaoFrete:
    tipo: str
    valor: Decimal  # o que o cliente paga (zero no Padrão acima do mínimo do frete grátis)
    custo: Decimal  # o que o envio custa para a loja
    prazo_dias: int


ROTULOS = {"PADRAO": "Padrão", "EXPRESSO": "Expresso"}


def somente_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def regiao_do_cep(cep: str | None) -> str | None:
    digitos = somente_digitos(cep)
    if len(digitos) != 8:
        return None
    numero = int(digitos)
    return next((regiao for inicio, fim, regiao in _FAIXAS if inicio <= numero <= fim), None)


def opcoes_de_frete(regiao, subtotal: Decimal, gratis_minimo: Decimal, expresso_ativo: bool) -> list[OpcaoFrete]:
    """Opções para uma região já configurada (m.FreteRegiao ou equivalente), na ordem Padrão, Expresso."""
    padrao_valor = Decimal("0") if subtotal >= gratis_minimo else regiao.padrao_valor
    opcoes = [OpcaoFrete("PADRAO", padrao_valor, regiao.padrao_custo, regiao.padrao_prazo_dias)]
    if expresso_ativo:
        opcoes.append(OpcaoFrete("EXPRESSO", regiao.expresso_valor, regiao.expresso_custo, regiao.expresso_prazo_dias))
    return opcoes


def uf_do_cep(cep: str | None) -> str | None:
    """UF aproximada pelo CEP, usada só para preferir a loja mais próxima na expedição."""
    prefixo = somente_digitos(cep)[:5]
    if len(prefixo) < 5:
        return None
    numero = int(prefixo)
    return next((uf for inicio, fim, uf in _FAIXAS_UF if inicio <= numero <= fim), None)


# Faixas de CEP (5 primeiros dígitos) dos estados que têm loja
_FAIXAS_UF = (
    (1000, 19999, "SP"),
    (20000, 28999, "RJ"),
    (30000, 39999, "MG"),
    (70000, 72799, "DF"),
    (73000, 73699, "DF"),
    (80000, 87999, "PR"),
)
