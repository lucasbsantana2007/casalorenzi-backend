"""Valores prontos para o texto (o modelo copia como vieram, sem fazer conta) e para os blocos da tela
(números crus + o formato, que o frontend aplica com o mesmo Intl do resto do site)."""

from datetime import date, datetime
from decimal import Decimal

from src.config.settings import FUSO
from src.utils.datas import ms
from src.utils.texto import moeda


def brl(valor) -> str:
    return moeda(valor)


def numero(valor) -> str:
    return f"{int(valor or 0):,}".replace(",", ".")


def pct(valor, casas: int = 1) -> str:
    texto = f"{float(valor or 0) * 100:.{casas}f}".replace(".", ",")
    return f"{texto}%"


def data(valor: date | datetime | None) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, datetime):
        valor = valor.astimezone(FUSO).date()
    return f"{valor:%d/%m/%Y}"


def cru(valor):
    """Decimal e datas para JSON (os blocos vão para o banco e para a tela)."""
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, datetime):
        return ms(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: cru(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [cru(v) for v in valor]
    return valor


# ---------- Blocos da tela ----------


def bloco_indicadores(itens: list[tuple[str, object, str]], titulo: str | None = None) -> dict:
    """itens: (rótulo, valor, formato) com formato moeda | numero | percentual | texto."""
    return {"tipo": "indicadores", "titulo": titulo, "itens": [{"rotulo": r, "valor": cru(v), "formato": f} for r, v, f in itens]}


def bloco_tabela(titulo: str, colunas: list[tuple[str, str, str]], linhas: list[dict], rodape: str | None = None) -> dict:
    """colunas: (chave, rótulo, formato). linhas: dicionários com as chaves das colunas."""
    return {
        "tipo": "tabela",
        "titulo": titulo,
        "colunas": [{"chave": c, "rotulo": r, "formato": f} for c, r, f in colunas],
        "linhas": [cru({c: linha.get(c) for c, _, _ in colunas}) for linha in linhas],
        "rodape": rodape,
    }


def bloco_grafico(titulo: str, forma: str, rotulo_x: str, series: list[dict], pontos: list[dict], formato: str = "moeda") -> dict:
    """forma: barras | linha. series: [{chave, rotulo}]. pontos: [{x, <chave>: valor}]."""
    return {
        "tipo": "grafico",
        "titulo": titulo,
        "forma": forma,
        "rotuloX": rotulo_x,
        "formato": formato,
        "series": series,
        "pontos": cru(pontos),
    }


def bloco_fonte(consulta: str, periodo: str | None, filtros: list[str], definicao: str, dados_ate: datetime | None) -> dict:
    """De onde veio o número: a consulta, o período, os filtros, a definição da métrica e a atualização."""
    return {
        "tipo": "fonte",
        "consulta": consulta,
        "periodo": periodo,
        "filtros": filtros,
        "definicao": definicao,
        "dadosAte": cru(dados_ate),
        "consultadoEm": ms(datetime.now(FUSO)),
    }
