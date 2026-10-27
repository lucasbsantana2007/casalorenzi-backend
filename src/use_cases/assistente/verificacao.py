"""Verificador de números das respostas do modelo (decisão 98).

"Ponto é dívida com o cliente. Se essa coisa disser que alguém tem mil pontos e ele tiver cem [...] o problema é
meu. Prefiro que ela diga 'não sei' do que invente." (CFO, no kickoff)

O modelo escreve a frase, mas todo número que importa precisa ter uma fonte. Antes de a resposta sair, o backend
separa os números do texto do modelo e confere cada um contra:
- fontes fortes: o resultado das ferramentas desta rodada (dados, blocos, texto e erros), as respostas anteriores
  da própria Lúcia, o contexto que o sistema montou (data, memória, lojas) e as instruções fixas (destas, só os
  números com unidade, como os "30 dias" da devolução: o "12." de uma regra numerada não é fonte de nada);
- fontes do usuário: o que o cliente escreveu (vale para tamanho, quantidade, data e códigos, nunca para dinheiro,
  pontos, percentual, parcelas ou prazo: "você tem 5.000 pontos" não pode sair só porque o cliente disse 5.000).

Número com unidade só vale para a mesma unidade ("12 dias" não é fonte de "12%"); número sem unidade (o saldo
1.200 de um campo "saldo") vale para qualquer uma. Ids, links e fotos não são fonte: "R$ 345" não pode passar
porque 345 é o id de uma peça.

Número sem fonte: o modelo tem uma chance de refazer a resposta (orquestrador) e, se errar de novo, a frase é
trocada pelo texto que as próprias ferramentas montaram ou por "não tenho essa informação confirmada". Sem modelo
de linguagem: é regra, testável e barata.

O que conta como número conferido: dinheiro (R$), pontos, percentual, parcelas (6x), prazos (dias, horas),
datas (27/10, 12 de novembro, dia 30), horários (10h, às 22), anos, códigos (pedido, protocolo, CEP, telefone) e
qualquer número de 11 para cima. Números pequenos soltos ("as 3 lojas", "a 2ª opção") são contagens da própria
frase e não são conferidos.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from src.utils.texto import normalizar

# Códigos: pedido e protocolo (CL-105093, ATD-026037), CEP (69000-000) e telefones ((31) 98413-9032)
_CODIGO = re.compile(r"\b[A-Za-z]{2,4}-\d{3,}\b|\b\d{5}-\d{3}\b|\(?\b\d{2}\)?\s?\d{4,5}-\d{4}\b")
_DATA = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_MESES = "janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro".split()
_DATA_EXTENSO = re.compile(
    r"\b(\d{1,2})(?:º|°)?\s+de\s+(janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
    r"(?:\s+de\s+(\d{4}))?\b",
    re.IGNORECASE,
)
# "no dia 30": só o dia
_DIA = re.compile(r"\bdia\s+(\d{1,2})\b", re.IGNORECASE)
_HORA = re.compile(r"\b(\d{1,2})(?::(\d{2})|h(\d{2})?)(?![\w])")
# 1.200 | 345.545,73 | 489 | 4,5
_NUMERO = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(?!\d)")

_DINHEIRO_ANTES = re.compile(r"r\$\s*$")
_DINHEIRO_DEPOIS = re.compile(r"^\s*(reais|real)\b")
_PERCENTUAL = re.compile(r"^\s*%")
_PARCELAS = re.compile(r"^\s*(x\b|vezes\b)")
_PONTOS = re.compile(r"^\s*(pontos?|pts)\b")
_PRAZO = re.compile(r"^\s*(dias?|mes|meses|horas?|h|minutos?|min|semanas?|anos?)\b")
_ESCALA = re.compile(r"^\s*(mil|milhao|milhoes)\b")
# "fecha às 22", "das 10 às 22": horário sem o "h"
_HORA_ANTES = re.compile(r"\b(as|das|ate as)\s*$")
# Número por extenso com unidade ("mil pontos", "trinta dias"): só passa se a fonte disser igual; senão o modelo
# reescreve em algarismos, que dá para conferir
_PALAVRA_NUMERO = (
    r"(?:dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|catorze|quatorze|quinze|dezesseis|dezessete|"
    r"dezoito|dezenove|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|duzent[oa]s|trezent[oa]s|"
    r"quatrocent[oa]s|quinhent[oa]s|seiscent[oa]s|setecent[oa]s|oitocent[oa]s|novecent[oa]s|mil|milhao|milhoes)"
)
_POR_EXTENSO = re.compile(
    rf"\b{_PALAVRA_NUMERO}(?:\s+(?:e\s+)?{_PALAVRA_NUMERO})*\s+(?:de\s+)?"
    r"(?:pontos?|pts|reais|dias|meses|horas|semanas|vezes|parcelas|por cento)\b"
)
# Ids e numeração do contexto do sistema: "(id 12)", "1: Loja Iguatemi", "1. Camisa Toscana"
_IDS = re.compile(r"\(id \d+\)|\bid \d+|(?<=[:;] )\d+(?=[:.] )|^\s*\d+\.(?= )", re.MULTILINE)
# Precisam de fonte forte: o cliente dizer um valor não o torna verdade
SENSIVEIS = frozenset({"dinheiro", "pontos", "percentual", "parcelas", "prazo"})


@dataclass
class Fontes:
    """Os números de uma ou mais fontes, já normalizados para comparar."""

    # Números sem unidade (o "1.200" do saldo, o preço 489.0 de um card): valem para qualquer tipo
    valores: set[Decimal] = field(default_factory=set)
    # Números com unidade só valem para a mesma unidade: "12 dias" não é fonte de "12%"
    tipados: dict[str, set[Decimal]] = field(default_factory=dict)
    # (dia, mês, ano); mês e ano podem faltar ("dia 30", "12/11")
    datas: set[tuple[int, int | None, int | None]] = field(default_factory=set)
    horas: set[tuple[int, int]] = field(default_factory=set)
    # Só os dígitos: "CL-105093" e "105093" são o mesmo pedido
    codigos: set[str] = field(default_factory=set)
    # Números por extenso da fonte ("a cada seis meses", no cuidado de uma peça)
    extensos: set[str] = field(default_factory=set)

    def juntar(self, outra: "Fontes") -> "Fontes":
        tipados = {t: set(v) for t, v in self.tipados.items()}
        for tipo, valores in outra.tipados.items():
            tipados.setdefault(tipo, set()).update(valores)
        return Fontes(
            self.valores | outra.valores,
            tipados,
            self.datas | outra.datas,
            self.horas | outra.horas,
            self.codigos | outra.codigos,
            self.extensos | outra.extensos,
        )

    def tem_data(self, dia: int, mes: int | None, ano: int | None) -> bool:
        if mes is None:
            return any(d == dia for d, _, _ in self.datas)
        if ano is None:
            return any((d, m) == (dia, mes) for d, m, _ in self.datas)
        return (dia, mes, ano) in self.datas or (dia, mes, None) in self.datas


@dataclass
class Numero:
    trecho: str
    tipo: str  # dinheiro, pontos, percentual, parcelas, prazo, geral, ano, data, hora, codigo, extenso
    valor: object


@dataclass
class Resultado:
    ok: bool
    sem_fonte: list[str] = field(default_factory=list)
    # Quantos números do texto foram conferidos
    conferidos: int = 0


def _ano(texto: str | None) -> int | None:
    if not texto:
        return None
    ano = int(texto)
    return ano + 2000 if ano < 100 else ano


def _valor(inteiro: str, centavos: str | None) -> Decimal | None:
    try:
        return Decimal(inteiro.replace(".", "") + (f".{centavos}" if centavos else ""))
    except InvalidOperation:
        return None


def _classificar(texto: str, inicio: int, fim: int, valor: Decimal, bruto: str) -> tuple[str | None, object]:
    """O tipo do número pelo que vem antes e depois dele (e o valor, já com o "mil" aplicado)."""
    antes = texto[max(0, inicio - 8) : inicio].lower()
    depois = normalizar(texto[fim : fim + 24])
    if escala := _ESCALA.match(depois):
        valor *= 1000 if escala.group(1) == "mil" else 1000000
        depois = depois[escala.end() :]
    if _DINHEIRO_ANTES.search(antes) or _DINHEIRO_DEPOIS.search(depois):
        return "dinheiro", valor
    if _PERCENTUAL.search(depois):
        return "percentual", valor
    if _PARCELAS.search(depois):
        return "parcelas", valor
    if _PONTOS.search(depois):
        return "pontos", valor
    if _PRAZO.search(depois):
        return "prazo", valor
    inteiro = "." not in bruto and "," not in bruto
    if inteiro and valor <= 23 and _HORA_ANTES.search(normalizar(antes)):
        return "hora", (int(valor), 0)
    if inteiro and 1990 <= valor <= 2100:
        return "ano", valor
    if valor >= 11 or not inteiro:
        return "geral", valor
    return None, valor  # contagem pequena da própria frase


def _separar(texto: str) -> tuple[list[Numero], str]:
    """Códigos, datas e horários do texto; devolve também o texto sem eles (para os números soltos não
    repetirem os dígitos de uma data ou de um código)."""
    achados: list[Numero] = []
    restante = texto

    def tirar(match) -> None:
        nonlocal restante
        a, b = match.span()
        restante = restante[:a] + " " * (b - a) + restante[b:]

    for m in _CODIGO.finditer(restante):
        achados.append(Numero(m.group(0), "codigo", re.sub(r"\D", "", m.group(0))))
        tirar(m)
    for m in _DATA.finditer(restante):
        dia, mes = int(m.group(1)), int(m.group(2))
        if 1 <= dia <= 31 and 1 <= mes <= 12:
            achados.append(Numero(m.group(0), "data", (dia, mes, _ano(m.group(3)))))
            tirar(m)
    for m in _DATA_EXTENSO.finditer(restante):
        dia, mes = int(m.group(1)), _MESES.index(normalizar(m.group(2))) + 1
        if 1 <= dia <= 31:
            achados.append(Numero(m.group(0), "data", (dia, mes, _ano(m.group(3)))))
            tirar(m)
    for m in _DIA.finditer(restante):
        if 1 <= (dia := int(m.group(1))) <= 31:
            achados.append(Numero(m.group(0), "data", (dia, None, None)))
            tirar(m)
    for m in _HORA.finditer(restante):
        hora, minuto = int(m.group(1)), int(m.group(2) or m.group(3) or 0)
        if hora <= 23 and minuto <= 59:
            achados.append(Numero(m.group(0), "hora", (hora, minuto)))
            tirar(m)
    return achados, restante


def _soltos(restante: str):
    """(trecho, tipo, valor) dos números que sobraram depois de separar códigos, datas e horários."""
    for m in _NUMERO.finditer(restante):
        if (valor := _valor(m.group(1), m.group(2))) is None:
            continue
        tipo, valor = _classificar(restante, m.start(), m.end(), valor, m.group(0))
        yield m.group(0), tipo, valor


def numeros_do_texto(texto: str) -> list[Numero]:
    """Os números de um texto em português, com o tipo de cada um."""
    achados, restante = _separar(texto)
    achados += [Numero(trecho, tipo, valor) for trecho, tipo, valor in _soltos(restante) if tipo]
    achados += [Numero(m.group(0), "extenso", m.group(0)) for m in _POR_EXTENSO.finditer(normalizar(restante))]
    return achados


def _e_id(chave) -> bool:
    return isinstance(chave, str) and (chave == "id" or chave.endswith("Id") or chave.endswith("_id"))


def _e_link(texto: str) -> bool:
    return texto.startswith(("http://", "https://", "/", "data:"))


def fontes_de(*objetos) -> Fontes:
    """Junta os números de textos, dicionários, listas e valores (o resultado das ferramentas, o contexto...)."""
    fontes = Fontes()

    def andar(valor) -> None:
        if valor is None or isinstance(valor, bool):
            return
        if isinstance(valor, str):
            if _e_link(valor):
                return
            especiais, restante = _separar(valor)
            for numero in especiais:
                {"codigo": fontes.codigos, "data": fontes.datas, "hora": fontes.horas}[numero.tipo].add(numero.valor)
            fontes.extensos.update(m.group(0) for m in _POR_EXTENSO.finditer(normalizar(restante)))
            # Todo número vale como fonte, inclusive os pequenos ("até 6x"), com a unidade que tiver
            for _, tipo, numero in _soltos(restante):
                if tipo == "hora":
                    fontes.horas.add(numero)
                elif tipo in SENSIVEIS:
                    fontes.tipados.setdefault(tipo, set()).add(numero)
                else:
                    fontes.valores.add(numero)
            return
        if isinstance(valor, (int, float, Decimal)):
            try:
                fontes.valores.add(Decimal(str(valor)))
            except InvalidOperation:
                pass
            return
        if isinstance(valor, (datetime, date)):
            fontes.datas.add((valor.day, valor.month, valor.year))
            return
        if isinstance(valor, dict):
            for chave, item in valor.items():
                if not _e_id(chave):
                    andar(item)
            return
        if isinstance(valor, (list, tuple, set)):
            for item in valor:
                andar(item)
            return
        andar(str(valor))

    for objeto in objetos:
        andar(objeto)
    return fontes


def fontes_com_unidade(*objetos) -> Fontes:
    """Só os números com unidade, as datas, os horários e os códigos (para as instruções fixas)."""
    fontes = fontes_de(*objetos)
    fontes.valores = set()
    return fontes


def sem_ids(texto: str) -> str:
    """O contexto do sistema sem os ids e a numeração das listas (não são números que o cliente vê)."""
    return _IDS.sub(" ", texto or "")


def _tem_fonte(numero: Numero, fontes: Fontes) -> bool:
    if numero.tipo == "codigo":
        digitos = numero.valor
        return (
            digitos in fontes.codigos
            or any(digitos in c or c in digitos for c in fontes.codigos if len(c) >= 4)
            or (digitos.isdigit() and Decimal(digitos) in fontes.valores)
        )
    if numero.tipo == "data":
        return fontes.tem_data(*numero.valor)
    if numero.tipo == "hora":
        return numero.valor in fontes.horas
    if numero.tipo == "extenso":
        return numero.valor in fontes.extensos
    if numero.valor in fontes.valores:
        return True
    if numero.tipo == "ano" and any(ano == numero.valor for _, _, ano in fontes.datas):
        return True
    if numero.tipo in SENSIVEIS:
        return numero.valor in fontes.tipados.get(numero.tipo, set())
    # Número solto que é parte de um código: "o pedido 105093" (CL-105093), "CEP 01310100"
    digitos = re.sub(r"\D", "", numero.trecho)
    if len(digitos) >= 4 and any(digitos in c for c in fontes.codigos):
        return True
    return any(numero.valor in valores for valores in fontes.tipados.values())


def conferir(texto: str, fortes: Fontes, do_usuario: Fontes | None = None) -> Resultado:
    """Confere os números do texto do modelo. ok=False lista os trechos sem fonte."""
    do_usuario = do_usuario or Fontes()
    numeros = numeros_do_texto(texto or "")
    sem_fonte = []
    for numero in numeros:
        if _tem_fonte(numero, fortes):
            continue
        if numero.tipo not in SENSIVEIS and _tem_fonte(numero, do_usuario):
            continue
        sem_fonte.append(numero.trecho.strip())
    return Resultado(ok=not sem_fonte, sem_fonte=list(dict.fromkeys(sem_fonte)), conferidos=len(numeros))


def descricoes(ferramentas) -> str:
    """Instruções que o modelo recebeu nas definições das ferramentas (também são fonte)."""
    return json.dumps([f.descricao for f in ferramentas], ensure_ascii=False)
