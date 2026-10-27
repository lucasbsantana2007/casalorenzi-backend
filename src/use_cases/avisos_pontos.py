"""Aviso por e-mail de pontos Lupe+ a vencer (decisão 82). Sem modelo de linguagem: é uma regra.

Todo dia (automação aviso_pontos), cada cliente com pontos vencendo nos próximos AVISO_VENCIMENTO_DIAS dias
recebe um e-mail, uma vez por data de vencimento:
- aviso de serviço, sem oferta, para todos os clientes com e-mail válido (não só quem aceita marketing);
- e-mail usado por mais de uma conta (familiares): o aviso sai sem saldo nem quantidade, para os pontos de uma
  pessoa não chegarem a outra;
- desligado por padrão (AVISO_PONTOS_ENVIAR). No modo teste (AVISO_PONTOS_TESTE_PARA), todos os avisos vão para
  o e-mail do time, com o cliente no assunto, no máximo AVISOS_TESTE_POR_DIA por dia;
- no máximo AVISO_PONTOS_LIMITE_DIA por dia (cota do Resend), com os vencimentos mais próximos primeiro;
- o aviso só é gravado depois que o e-mail saiu, numa transação própria: um erro no meio não faz ninguém
  receber de novo, e uma falha de envio fica para o dia seguinte.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src import models as m
from src.config import settings
from src.database.connection import SessionLocal
from src.entities import fidelidade as regra
from src.entities.cliente import email_valido, normalizar_email
from src.integrations import email as envio
from src.integrations import modelos_email
from src.repositories import fidelidade_repository
from src.use_cases.fidelidade import lotes_em_aberto
from src.utils.datas import agora, hoje, inicio_do_dia

log = logging.getLogger("casalorenzi.avisos")

# Pausa entre dois e-mails: a API do Resend aceita poucas chamadas por segundo
PAUSA_ENTRE_ENVIOS = 0.6


@dataclass
class Pendente:
    cliente: m.Cliente
    # Pontos que vencem na janela, por data (todos vão no e-mail)
    vencimentos: list[tuple[date, int]]
    # As datas que ainda não tinham sido avisadas (são as gravadas)
    novos: list[tuple[date, int]]
    saldo: int
    compartilhado: bool


@dataclass
class Resultado:
    ligado: bool
    modo: str | None = None
    pendentes: int = 0
    enviados: int = 0
    sem_numeros: int = 0
    falhas: int = 0
    adiados: int = 0
    detalhe: list[str] = field(default_factory=list)


def _modo() -> str:
    return "TESTE" if settings.AVISO_PONTOS_TESTE_PARA else "REAL"


def _emails_compartilhados(db: Session) -> set[str]:
    consulta = (
        select(m.Cliente.email)
        .where(m.Cliente.email.is_not(None), m.Cliente.excluido_em.is_(None))
        .group_by(m.Cliente.email)
        .having(func.count() > 1)
    )
    return {normalizar_email(email) for email in db.scalars(consulta)}


def pendentes(db: Session, modo: str, referencia: date | None = None) -> list[Pendente]:
    """Clientes com e-mail válido e pontos vencendo na janela que ainda não foram avisados dessas datas,
    do vencimento mais próximo para o mais distante. Só lê: não lança o vencimento de ninguém."""
    referencia = referencia or hoje()
    limite = referencia + timedelta(days=regra.AVISO_VENCIMENTO_DIAS)
    por_cliente: dict[int, list] = defaultdict(list)
    for mov in fidelidade_repository.movimentos_de_todos(db):
        por_cliente[mov.cliente_id].append(mov)
    janelas: dict[int, tuple[list[tuple[date, int]], int]] = {}
    for cliente_id, movimentos in por_cliente.items():
        lotes = lotes_em_aberto(movimentos)
        vencendo: dict[date, int] = defaultdict(int)
        for vence, pontos in lotes:
            if referencia <= vence <= limite:
                vencendo[vence] += pontos
        if vencendo:
            saldo = sum(pontos for vence, pontos in lotes if vence >= referencia)
            janelas[cliente_id] = (sorted(vencendo.items()), saldo)
    if not janelas:
        return []
    consulta = select(m.AvisoPontos.cliente_id, m.AvisoPontos.vencimento).where(
        m.AvisoPontos.modo == modo, m.AvisoPontos.vencimento >= referencia, m.AvisoPontos.cliente_id.in_(janelas)
    )
    avisados = {(cliente_id, dia) for cliente_id, dia in db.execute(consulta)}
    compartilhados = _emails_compartilhados(db)
    clientes = db.scalars(select(m.Cliente).where(m.Cliente.id.in_(janelas), m.Cliente.excluido_em.is_(None)))
    saida = []
    for cliente in clientes:
        if not email_valido(cliente.email):
            continue
        vencimentos, saldo = janelas[cliente.id]
        novos = [(dia, pontos) for dia, pontos in vencimentos if (cliente.id, dia) not in avisados]
        if novos:
            compartilhado = normalizar_email(cliente.email) in compartilhados
            saida.append(Pendente(cliente, vencimentos, novos, saldo, compartilhado))
    return sorted(saida, key=lambda p: (p.novos[0][0], p.cliente.id))


def montar_email(pendente: Pendente, teste_para: str | None = None) -> envio.Email:
    cliente = pendente.cliente
    if pendente.compartilhado:
        email = modelos_email.aviso_pontos_sem_numeros(cliente.email, cliente.nome)
    else:
        categoria = regra.categoria_pelo_saldo(pendente.saldo)
        email = modelos_email.aviso_pontos(
            cliente.email, cliente.nome, pendente.vencimentos, pendente.saldo, categoria, regra.proxima_categoria(pendente.saldo)
        )
    if teste_para:
        assunto = f"[Teste · para {cliente.email}] {email.assunto}"
        return envio.Email(para=teste_para, assunto=assunto, texto=email.texto, html=email.html)
    return email


def _enviar_de_verdade(email: envio.Email) -> None:
    """Espera a resposta do Resend (o aviso só é gravado se saiu). Sem RESEND_API_KEY, vai para o log."""
    if not envio.RESEND_API_KEY:
        log.info("Aviso de pontos (sem RESEND_API_KEY, não enviado) para %s · %s\n%s", email.para, email.assunto, email.texto)
        return
    envio.enviar_agora(email)


def _enviados_hoje(db: Session, modo: str) -> int:
    consulta = select(func.count(func.distinct(m.AvisoPontos.cliente_id))).where(
        m.AvisoPontos.modo == modo, m.AvisoPontos.enviado_em >= inicio_do_dia(hoje())
    )
    return int(db.scalar(consulta) or 0)


def _gravar(pendente: Pendente, modo: str, para: str) -> None:
    """Numa sessão própria, logo depois do envio: o aviso que saiu fica gravado mesmo que algo falhe depois."""
    momento = agora()
    with SessionLocal() as gravacao:
        gravacao.add_all(
            m.AvisoPontos(
                cliente_id=pendente.cliente.id,
                vencimento=dia,
                pontos=pontos,
                modo=modo,
                email=para,
                sem_numeros=pendente.compartilhado,
                enviado_em=momento,
            )
            for dia, pontos in pendente.novos
        )
        try:
            gravacao.commit()
        except IntegrityError:
            # Outra execução gravou o mesmo aviso ao mesmo tempo: a chave única segurou a repetição
            gravacao.rollback()


def enviar_pendentes(db: Session, enviar: Callable[[envio.Email], None] | None = None) -> Resultado:
    """Manda os avisos do dia. enviar: troca o envio (testes)."""
    if not settings.AVISO_PONTOS_ENVIAR:
        return Resultado(ligado=False, detalhe=["envio desligado (AVISO_PONTOS_ENVIAR)"])
    enviar = enviar or _enviar_de_verdade
    modo = _modo()
    teste_para = settings.AVISO_PONTOS_TESTE_PARA or None
    teto = regra.AVISOS_TESTE_POR_DIA if teste_para else settings.AVISO_PONTOS_LIMITE_DIA
    lista = pendentes(db, modo)
    vagas = max(teto - _enviados_hoje(db, modo), 0)
    resultado = Resultado(ligado=True, modo=modo, pendentes=len(lista), adiados=max(len(lista) - vagas, 0))
    for indice, pendente in enumerate(lista[:vagas]):
        email = montar_email(pendente, teste_para)
        if indice:
            time.sleep(PAUSA_ENTRE_ENVIOS)
        try:
            enviar(email)
        except Exception:
            resultado.falhas += 1
            log.exception("Falha ao enviar o aviso de pontos do cliente %s", pendente.cliente.id)
            continue
        _gravar(pendente, modo, email.para)
        resultado.enviados += 1
        resultado.sem_numeros += pendente.compartilhado
    resultado.detalhe.append(
        f"modo {modo}: {resultado.enviados} aviso(s) enviado(s)"
        + ("" if envio.RESEND_API_KEY or enviar is not _enviar_de_verdade else " (sem RESEND_API_KEY: só no log)")
        + (f", {resultado.sem_numeros} sem o saldo (e-mail compartilhado)" if resultado.sem_numeros else "")
        + (f", {resultado.falhas} falha(s)" if resultado.falhas else "")
        + (f", {resultado.adiados} para os próximos dias (limite diário)" if resultado.adiados else "")
    )
    return resultado
