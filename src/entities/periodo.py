"""Períodos que o copiloto entende ("hoje", "mês passado", "setembro"), em datas do fuso da plataforma
(FUSO_HORARIO). O período vai de inicio a fim, os dois dias inclusos, como os filtros do financeiro."""

from dataclasses import dataclass
from datetime import date, timedelta

from src.utils.erros import DadosInvalidos

PERIODOS = (
    "hoje",
    "ontem",
    "semana_atual",
    "semana_passada",
    "mes_atual",
    "mes_passado",
    "ultimos_7_dias",
    "ultimos_30_dias",
    "ultimos_90_dias",
    "ano_atual",
    "ano_passado",
    "personalizado",
)
PERIODO_PADRAO = "mes_atual"
# Consultas mais longas que isso pesam demais (o financeiro carrega os pedidos do período)
DURACAO_MAXIMA_DIAS = 400

MESES = (
    "janeiro",
    "fevereiro",
    "marco",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
NOMES_MESES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


@dataclass(frozen=True)
class Periodo:
    inicio: date
    fim: date
    nome: str

    @property
    def dias(self) -> int:
        return (self.fim - self.inicio).days + 1

    @property
    def frase(self) -> str:
        """'em 26/10/2026' ou 'de 01/09/2026 a 30/09/2026', para o meio de uma frase."""
        return f"em {self.inicio:%d/%m/%Y}" if self.inicio == self.fim else f"de {self.rotulo}"

    @property
    def rotulo(self) -> str:
        if self.inicio == self.fim:
            return f"{self.inicio:%d/%m/%Y}"
        return f"{self.inicio:%d/%m/%Y} a {self.fim:%d/%m/%Y}"


def _inicio_do_mes(dia: date) -> date:
    return dia.replace(day=1)


def _fim_do_mes(dia: date) -> date:
    return (dia.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def resolver(nome: str | None, hoje: date, de: date | None = None, ate: date | None = None) -> Periodo:
    """Datas do período pedido. 'personalizado' usa de/ate (sem data final: até hoje)."""
    nome = nome or PERIODO_PADRAO
    if nome not in PERIODOS:
        raise DadosInvalidos(f"Período desconhecido: {nome}.")
    segunda = hoje - timedelta(days=hoje.weekday())
    if nome == "hoje":
        inicio, fim = hoje, hoje
    elif nome == "ontem":
        inicio = fim = hoje - timedelta(days=1)
    elif nome == "semana_atual":
        inicio, fim = segunda, hoje
    elif nome == "semana_passada":
        inicio, fim = segunda - timedelta(days=7), segunda - timedelta(days=1)
    elif nome == "mes_atual":
        inicio, fim = _inicio_do_mes(hoje), hoje
    elif nome == "mes_passado":
        fim = _inicio_do_mes(hoje) - timedelta(days=1)
        inicio = _inicio_do_mes(fim)
    elif nome.startswith("ultimos_"):
        dias = int(nome.split("_")[1])
        inicio, fim = hoje - timedelta(days=dias - 1), hoje
    elif nome == "ano_atual":
        inicio, fim = hoje.replace(month=1, day=1), hoje
    elif nome == "ano_passado":
        inicio, fim = date(hoje.year - 1, 1, 1), date(hoje.year - 1, 12, 31)
    else:
        if de is None:
            raise DadosInvalidos("Informe a data inicial do período.")
        inicio, fim = de, ate or hoje
    if fim < inicio:
        raise DadosInvalidos("A data final deve ser igual ou posterior à inicial.")
    if (fim - inicio).days + 1 > DURACAO_MAXIMA_DIAS:
        raise DadosInvalidos(f"Escolha um período de até {DURACAO_MAXIMA_DIAS} dias.")
    return Periodo(inicio, fim, nome)


def mes(numero: int, ano: int) -> Periodo:
    """O mês inteiro (setembro de 2026: 01/09/2026 a 30/09/2026)."""
    inicio = date(ano, numero, 1)
    return Periodo(inicio, _fim_do_mes(inicio), "personalizado")
