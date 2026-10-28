"""Aba Lupe+ do Atendimento (decisão 120): quantos pontos cada cliente tem, para a equipe que atende (Administrador e
Lojista, os mesmos que veem a ficha do cliente).

O saldo é o mesmo da ficha do cliente e dos números do programa: as entradas ainda não gastas que não venceram
(pontos vencidos e ainda não baixados ficam de fora). Só calcula: não lança o vencimento de ninguém.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import models as m
from src.entities import fidelidade as regra
from src.entities.cliente import somente_digitos_cpf
from src.repositories import fidelidade_repository
from src.use_cases.fidelidade import lotes_em_aberto
from src.utils.datas import hoje
from src.utils.erros import DadosInvalidos
from src.utils.texto import normalizar

ORDENS = ("saldo", "nome", "vencimento")


@dataclass
class LinhaLupe:
    cliente: m.Cliente
    saldo: int
    categoria: str | None
    proximo_vencimento: tuple[date, int] | None


def _saldos(db: Session, referencia: date) -> dict[int, tuple[int, tuple[date, int] | None]]:
    """cliente_id -> (saldo válido, (próximo vencimento, pontos)) de quem tem pontos."""
    por_cliente: dict[int, list] = defaultdict(list)
    for mov in fidelidade_repository.movimentos_de_todos(db):
        por_cliente[mov.cliente_id].append(mov)
    saldos = {}
    for cliente_id, movimentos in por_cliente.items():
        validos = [(vence, pontos) for vence, pontos in lotes_em_aberto(movimentos) if vence >= referencia and pontos > 0]
        saldo = sum(pontos for _, pontos in validos)
        if saldo <= 0:
            continue
        primeiro = min(vence for vence, _ in validos)
        saldos[cliente_id] = (saldo, (primeiro, sum(p for v, p in validos if v == primeiro)))
    return saldos


def _corresponde(cliente: m.Cliente, termo: str, digitos: str) -> bool:
    if termo in normalizar(cliente.nome) or termo in normalizar(cliente.email or ""):
        return True
    return len(digitos) >= 3 and digitos in (cliente.cpf or "")


def listar(
    db: Session, *, busca: str | None = None, categoria: str | None = None, ordem: str = "saldo", referencia: date | None = None
) -> dict:
    """Clientes com pontos válidos, com o resumo do que a lista mostra. busca: nome, e-mail ou CPF."""
    if categoria and categoria not in regra.CATEGORIAS_FIDELIDADE:
        raise DadosInvalidos("Categoria inválida.")
    if ordem not in ORDENS:
        raise DadosInvalidos("Ordem inválida.")
    referencia = referencia or hoje()
    saldos = _saldos(db, referencia)
    clientes = db.scalars(select(m.Cliente).where(m.Cliente.id.in_(saldos), m.Cliente.excluido_em.is_(None))) if saldos else []
    termo = normalizar((busca or "").strip())
    digitos = somente_digitos_cpf(busca)
    linhas = []
    for cliente in clientes:
        if termo and not _corresponde(cliente, termo, digitos):
            continue
        saldo, proximo = saldos[cliente.id]
        cat = regra.categoria_pelo_saldo(saldo)
        if categoria and cat != categoria:
            continue
        linhas.append(LinhaLupe(cliente, saldo, cat, proximo))
    if ordem == "nome":
        linhas.sort(key=lambda linha: normalizar(linha.cliente.nome))
    elif ordem == "vencimento":
        linhas.sort(key=lambda linha: (linha.proximo_vencimento or (date.max, 0))[0])
    else:
        linhas.sort(key=lambda linha: (-linha.saldo, normalizar(linha.cliente.nome)))
    pontos = sum(linha.saldo for linha in linhas)
    return {
        "referencia": referencia,
        "clientes": len(linhas),
        "pontos": pontos,
        "valorEmReais": regra.valor_em_reais(pontos),
        "linhas": linhas,
    }
