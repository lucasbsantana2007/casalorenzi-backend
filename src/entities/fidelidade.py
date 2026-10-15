"""Vulto+ (programa de pontos da Vulto). Conta de pontos por cliente (pontos só com CPF) e o
extrato em movimentos com quantidade com sinal: positiva entra, negativa sai. O saldo da conta é
a soma dos movimentos e nunca fica negativo.

Regras (aba LEIA ISSO da planilha de clientes, jun/2025): 1 ponto por R$1 na loja física, dobro no
site/app, Ouro +50%; validade de 12 meses (Ouro 18, combinado com o Diego); 100 pontos = R$5 desde
mar/2025 (eram R$10); categoria pelos pontos acumulados no ano."""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

CATEGORIAS_FIDELIDADE = ("BRONZE", "PRATA", "OURO")

TIPOS_MOVIMENTO_PONTOS = ("SALDO_INICIAL", "CREDITO", "RESGATE", "ESTORNO", "AJUSTE", "VENCIMENTO")

# Sinal da quantidade de cada tipo: 1 só entra, -1 só sai, 0 aceita os dois
SINAL_POR_TIPO = {
    "SALDO_INICIAL": 1,
    "CREDITO": 1,
    "RESGATE": -1,
    "ESTORNO": -1,
    "AJUSTE": 0,
    "VENCIMENTO": -1,
}

# pontos_mov.tipo do legado: C crédito, D resgate, E estorno (já vem negativo), AJ ajuste manual
TIPO_POR_CODIGO_LEGADO = {"C": "CREDITO", "D": "RESGATE", "E": "ESTORNO", "AJ": "AJUSTE"}


def restricao_sinal() -> str:
    """Condição SQL que obriga cada tipo a respeitar o próprio sinal (e nenhuma quantidade zero)."""
    entram = ", ".join(f"'{t}'" for t, s in SINAL_POR_TIPO.items() if s == 1)
    saem = ", ".join(f"'{t}'" for t, s in SINAL_POR_TIPO.items() if s == -1)
    return f"quantidade <> 0 AND (tipo NOT IN ({entram}) OR quantidade > 0) AND (tipo NOT IN ({saem}) OR quantidade < 0)"


FUSO = ZoneInfo("America/Sao_Paulo")

# Categoria pelos pontos creditados no ano civil (líquidos de estornos): Bronze até 1.999, Prata 2.000 a 4.999
FAIXAS_CATEGORIA = ((5000, "OURO"), (2000, "PRATA"), (0, "BRONZE"))

# Validade em meses. O Ouro 18 foi combinado com o Diego e "não está no sistema"; é o cenário gravado
VALIDADE_MESES = 12
VALIDADE_MESES_OURO = (12, 18)
VALIDADE_OURO_GRAVADA = 18

# Valor do ponto em reais: o vigente (R$5 por 100 pontos desde mar/2025) e o antigo (R$10 por 100), que
# continua no config.valor_ponto e no README do sistema da Vulto e que a maioria dos resgates seguiu dando
VALOR_PONTO_VIGENTE = Decimal("0.05")
VALOR_PONTO_ANTIGO = Decimal("0.10")
VALOR_PONTO_MUDOU_EM = date(2025, 3, 1)
BONUS_OURO = Decimal("0.5")

# Data do passivo: a virada da Vulto para a plataforma
DATA_VIRADA = date(2026, 10, 1)


def categoria_pela_regra(pontos_no_ano: int) -> str:
    """Estorno de crédito do ano anterior pode deixar o ano negativo: Bronze."""
    return next(nome for minimo, nome in FAIXAS_CATEGORIA if max(pontos_no_ano, 0) >= minimo)


def validade_meses(categoria: str | None, ouro_meses: int = VALIDADE_OURO_GRAVADA) -> int:
    return ouro_meses if categoria == "OURO" else VALIDADE_MESES


def somar_meses(momento: datetime, meses: int) -> date:
    """Dia em que vence (o mesmo dia do mês, meses depois; dia 29 a 31 vira o último dia que existe)."""
    ano, mes = divmod(momento.astimezone(FUSO).month - 1 + meses, 12)
    ano += momento.astimezone(FUSO).year
    dia = momento.astimezone(FUSO).day
    while True:
        try:
            return date(ano, mes + 1, dia)
        except ValueError:
            dia -= 1


@dataclass
class Validade:
    saldo: int
    vencimentos: list[tuple[datetime, int]]  # (quando venceu, pontos)
    faltas: list[tuple[datetime, int]]  # saídas sem saldo disponível (o legado deixava o saldo ficar negativo)
    a_vencer: list[tuple[date, int]]  # o saldo por data de vencimento (mais próxima primeiro)


def aplicar_validade(movimentos: list[tuple[datetime, int]], meses: int, ate: datetime) -> Validade:
    """Saldo em `ate` com validade FIFO. Cada entrada é um lote que vence em `meses`; cada saída consome
    os lotes mais antigos; o que sobra num lote na data de vencimento sai como vencimento. Saída maior que
    o disponível consome o que há e o resto fica em `faltas` (o saldo para em zero)."""
    lotes: list[list] = []  # [vence_em (momento), restante]
    vencimentos: list[tuple[datetime, int]] = []
    faltas: list[tuple[datetime, int]] = []

    def vencer(ate_momento: datetime) -> None:
        for lote in lotes:
            if lote[1] > 0 and lote[0] <= ate_momento:
                vencimentos.append((lote[0], lote[1]))
                lote[1] = 0

    # No mesmo instante, entradas antes das saídas
    for quando, quantidade in sorted(movimentos, key=lambda mv: (mv[0], mv[1] < 0)):
        if quando > ate:
            break
        vencer(quando)
        if quantidade > 0:
            lotes.append([datetime.combine(somar_meses(quando, meses), time(0), FUSO), quantidade])
            continue
        falta = -quantidade
        for lote in lotes:  # já em ordem de vencimento (entram em ordem de data, com a mesma validade)
            usa = min(falta, lote[1])
            lote[1] -= usa
            falta -= usa
            if not falta:
                break
        if falta:
            faltas.append((quando, falta))
    vencer(ate)
    vencimentos.sort()
    a_vencer: dict[date, int] = {}
    for vence, restante in lotes:
        if restante:
            a_vencer[vence.date()] = a_vencer.get(vence.date(), 0) + restante
    return Validade(sum(lote[1] for lote in lotes), vencimentos, faltas, sorted(a_vencer.items()))
